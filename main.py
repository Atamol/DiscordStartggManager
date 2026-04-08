import os
import asyncio
import json
import re
import time
import requests
import functools
import logging
from typing import Optional

import discord
from discord import Embed, app_commands
from discord.ext import tasks, commands

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("DiscordStartggManager")

DISCORD_BOT_TOKEN  = os.getenv("DISCORD_BOT_TOKEN")
STARTGG_API_TOKEN  = os.getenv("STARTGG_API_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
TOURNAMENT_SLUG    = os.getenv("TOURNAMENT_SLUG")
MAX_SCORE          = int(os.getenv("MAX_SCORE", "3"))
STREAM_NUMBER      = int(os.getenv("STREAM_NUMBER", "1"))

REQUIRED = {
    "DISCORD_BOT_TOKEN": DISCORD_BOT_TOKEN,
    "STARTGG_API_TOKEN": STARTGG_API_TOKEN,
    "DISCORD_CHANNEL_ID": os.getenv("DISCORD_CHANNEL_ID"),
    "TOURNAMENT_SLUG": TOURNAMENT_SLUG,
}
missing = [k for k, v in REQUIRED.items() if not v or str(v).strip() == ""]
if missing:
    raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

GQL_ENDPOINT  = "https://api.start.gg/gql/alpha"
POLL_INTERVAL = 2
MAX_RETRIES   = 3

initial_scan_done = False
station_map: dict[str, str] = {}
active_views: dict[str, dict] = {}
completed_set_ids: set[str] = set()


# start.gg: 80 req/60s
class RateLimiter:
    def __init__(self, max_requests: int = 70, window: float = 60.0):
        self.max_requests = max_requests
        self.window = window
        self._timestamps: list[float] = []

    async def acquire(self):
        while True:
            now = time.monotonic()
            self._timestamps = [t for t in self._timestamps if now - t < self.window]
            if len(self._timestamps) < self.max_requests:
                self._timestamps.append(now)
                return
            wait = self.window - (now - self._timestamps[0]) + 0.1
            logger.warning(f"Rate limit throttle: waiting {wait:.1f}s ({len(self._timestamps)}/{self.max_requests})")
            await asyncio.sleep(wait)

    @property
    def remaining(self) -> int:
        now = time.monotonic()
        active = sum(1 for t in self._timestamps if now - t < self.window)
        return max(0, self.max_requests - active)

rate_limiter = RateLimiter(max_requests=70, window=60.0)

GET_PARTICIPANTS_QUERY = """
query GetEntrants($slug: String!) {
  tournament(slug: $slug) {
    events {
      entrants {
        nodes {
          name
          participants {
            gamerTag
            user {
              authorizations {
                type
                externalId
              }
            }
          }
        }
      }
    }
  }
}
"""

# 未完了セット (state: 1=Created, 2=Started, 6=Called) -- 台割り当て検知用
QUERY_ACTIVE_SETS = """
query GetActiveSets($slug: String!, $page: Int!) {
  tournament(slug: $slug) {
    events {
      sets(page: $page, perPage: 50, sortType: STANDARD, filters: { state: [1, 2, 6] }) {
        nodes {
          id
          fullRoundText
          state
          winnerId
          station { number }
          games { winnerId }
          slots {
            entrant {
              id
              name
              participants {
                gamerTag
                user { authorizations { type externalId } }
              }
            }
          }
        }
      }
    }
  }
}
"""

# 完了セットの差分取得 (state:3, updatedAfter)
QUERY_COMPLETED_SETS = """
query GetCompletedSets($slug: String!, $page: Int!, $updatedAfter: Timestamp!) {
  tournament(slug: $slug) {
    events {
      sets(page: $page, perPage: 50, sortType: STANDARD, filters: { state: [3], updatedAfter: $updatedAfter }) {
        nodes {
          id
          fullRoundText
          state
          winnerId
          station { number }
          games { winnerId }
          slots {
            entrant {
              id
              name
              participants {
                gamerTag
                user { authorizations { type externalId } }
              }
            }
          }
        }
      }
    }
  }
}
"""

# 初回スキャン用 (フィルタなし)
QUERY_ALL_SETS = """
query GetSets($slug: String!, $page: Int!) {
  tournament(slug: $slug) {
    events {
      sets(page: $page, perPage: 50, sortType: STANDARD) {
        nodes {
          id
          fullRoundText
          state
          winnerId
          station { number }
          games { winnerId }
          slots {
            entrant {
              id
              name
              participants {
                gamerTag
                user { authorizations { type externalId } }
              }
            }
          }
        }
      }
    }
  }
}
"""

MUT_REPORT_SET = """
mutation Report(
  $setId: ID!
  $winnerId: ID!
  $gameData: [BracketSetGameDataInput!]!
) {
  reportBracketSet(
    setId: $setId
    winnerId: $winnerId
    gameData: $gameData
  ) {
    id
    state
  }
}
"""

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=";", intents=intents)

def gql_sync(query: str, variables: dict):
    headers = {
        "Authorization": f"Bearer {STARTGG_API_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = None
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.post(
            GQL_ENDPOINT,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=15,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            logger.warning(f"429 Rate Limited (attempt {attempt}/{MAX_RETRIES}), retry after {retry_after}s")
            time.sleep(retry_after)
            continue
        if resp.status_code >= 500:
            logger.warning(f"Server error {resp.status_code} (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(2 * attempt)
            continue
        break
    else:
        raise RuntimeError(f"start.gg API failed after {MAX_RETRIES} retries (last status: {resp.status_code if resp else 'N/A'})")

    data = resp.json()
    if "errors" in data:
        raise RuntimeError(json.dumps(data["errors"], indent=2, ensure_ascii=False))
    return data


async def gql_async(query: str, variables: dict, timeout_sec: int = 30):
    await rate_limiter.acquire()
    loop = asyncio.get_running_loop()
    fn = functools.partial(gql_sync, query, variables)
    return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout_sec)

def mention(part: dict) -> str:
    user = part.get("user")
    if not user:
        return part.get("gamerTag", "Unknown")
    for auth in user.get("authorizations", []):
        if auth.get("type") == "DISCORD":
            ext_id = auth.get("externalId")
            if ext_id and ext_id.isdigit():
                return f"<@!{ext_id}>"
    return part.get("gamerTag", "Unknown")


def render_with_scores(text: str, s1: Optional[int], s2: Optional[int]) -> str:
    lines = text.splitlines()
    output = []
    p1_done = p2_done = False
    for line in lines:
        if "(" in line:
            if not p1_done:
                line = re.sub(r"\(\d+\)", f"({s1 or 0})", line, count=1)
                p1_done = True
            elif not p2_done:
                line = re.sub(r"\(\d+\)", f"({s2 or 0})", line, count=1)
                p2_done = True
        output.append(line)
    return "\n".join(output)


def format_result_message(action: str, preposition: str, members: list[str], role: discord.Role) -> str:
    if not members:
        return "⚠️ 該当ユーザーが見つかりませんでした。"
    return f"✅ 以下の {len(members)}名 {preposition}ロール `{role.name}` を{action}しました:\n\n" + \
           "\n".join(f"- {m}" for m in members)

async def update_finished_match_ui(set_node: dict):
    set_id = set_node["id"]
    view_info = active_views.get(set_id)
    if not view_info:
        return

    message = view_info.get("message")
    view = view_info.get("view")
    slots = view_info.get("slots")
    if not message or not view or not slots or len(slots) < 2:
        return

    try:
        entrant1 = slots[0]["entrant"]
        entrant2 = slots[1]["entrant"]
        entrant1_id = entrant1["id"]
        entrant2_id = entrant2["id"]
        name1 = entrant1["participants"][0]["gamerTag"]
        name2 = entrant2["participants"][0]["gamerTag"]
    except (KeyError, IndexError):
        return

    games = set_node.get("games")
    winner_id = set_node.get("winnerId")

    embed = message.embeds[0].copy()
    round_text = f"🏷️ {set_node.get('fullRoundText', '不明なラウンド')}"
    station_val = set_node.get("station", {}).get("number", "?")
    try:
        station_i = int(station_val)
    except (TypeError, ValueError):
        station_i = 9999
    if station_i == 1:
        station_text = "🖥️ **Station 1** 🎥**配信台**"
    elif station_i <= STREAM_NUMBER:
        station_text = f"🖥️ **Station {station_i}** 🎥**サブ配信台**"
    else:
        station_text = f"🖥️ **Station {station_i}**"

    if not games:
        if winner_id == entrant1_id:
            winner, loser = name1, name2
        elif winner_id == entrant2_id:
            winner, loser = name2, name1
        else:
            return
        new_desc = (
            "✅ **この試合は終了しました\n（スタッフにより処理されました）**\n\n"
            f"{round_text}\n\n"
            f"{station_text}\n\n"
            f"{winner} (**WIN**)\nvs\n{loser} (**LOSE**)"
        )
        embed.description = new_desc
    else:
        score1 = sum(1 for g in games if g.get("winnerId") == entrant1_id)
        score2 = sum(1 for g in games if g.get("winnerId") == entrant2_id)
        embed.description = render_with_scores(embed.description, score1, score2)
        embed.description = "✅ **この試合は終了しました**\n\n" + embed.description

    for item in view.children:
        item.disabled = True
    await message.edit(embed=embed, view=view)
    active_views.pop(set_id, None)


async def fetch_discord_ids_from_startgg() -> list[tuple[int, str]]:
    data = await gql_async(GET_PARTICIPANTS_QUERY, {"slug": TOURNAMENT_SLUG})
    all_data = []
    for event in data["data"]["tournament"]["events"]:
        for entrant in event.get("entrants", {}).get("nodes", []):
            for participant in entrant.get("participants", []):
                tag = participant.get("gamerTag", "Unknown")
                user = participant.get("user")
                if not user:
                    continue
                for auth in user.get("authorizations", []):
                    if auth.get("type") == "DISCORD":
                        ext_id = auth.get("externalId")
                        if ext_id and ext_id.isdigit():
                            all_data.append((int(ext_id), tag))
    return all_data

class FallbackScoreBtn(discord.ui.Button):
    def __init__(self, player: int, score: int, row: int):
        super().__init__(label=str(score), style=discord.ButtonStyle.secondary, custom_id=f"s{player}_{score}", row=row)
    async def callback(self, inter: discord.Interaction):
        await inter.response.send_message("このボタンは再起動により無効になりました。最新の投稿をご利用ください。", ephemeral=True)

class FallbackOkBtn(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="OK", style=discord.ButtonStyle.success, custom_id="ok", row=row)
    async def callback(self, inter: discord.Interaction):
        await inter.response.send_message("このボタンは再起動により無効になりました。最新の投稿をご利用ください。", ephemeral=True)

class FallbackReportView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for s in range(MAX_SCORE + 1):
            self.add_item(FallbackScoreBtn(1, s, row=0))
        for s in range(MAX_SCORE + 1):
            self.add_item(FallbackScoreBtn(2, s, row=1))
        self.add_item(FallbackOkBtn(row=2))

class ReportButtons(discord.ui.View):
    def __init__(self, set_id: str, p1_id: int, p2_id: int):
        super().__init__(timeout=None)
        self.set_id = set_id
        self.p1_id = p1_id
        self.p2_id = p2_id
        self.s1: Optional[int] = 0
        self.s2: Optional[int] = 0

        for s in range(MAX_SCORE + 1):
            self.add_item(ScoreBtn(1, s, row=0))
        for s in range(MAX_SCORE + 1):
            self.add_item(ScoreBtn(2, s, row=1))
        self.add_item(OkBtn(row=2))

    async def update_score(self, inter: discord.Interaction, player: int, score: int, pressed_button: discord.ui.Button):
        if player == 1:
            self.s1 = score
        else:
            self.s2 = score

        for item in self.children:
            if isinstance(item, ScoreBtn) and item.player == player:
                item.style = (
                    discord.ButtonStyle.success if item.score == score
                    else discord.ButtonStyle.secondary
                )

        await inter.response.defer()
        embed = inter.message.embeds[0].copy()
        embed.description = render_with_scores(embed.description, self.s1 or 0, self.s2 or 0)
        await inter.message.edit(embed=embed, view=self)

    async def send(self, inter: discord.Interaction):
        if self.s1 == self.s2:
            await inter.response.send_message("スコアが同点です。", ephemeral=True)
            return

        if self.set_id not in active_views:
            await inter.response.send_message("この試合はすでに処理済みです。", ephemeral=True)
            return

        slots = active_views[self.set_id]["slots"]
        entrant1_id = slots[0]["entrant"]["id"]
        entrant2_id = slots[1]["entrant"]["id"]

        score_map = {self.p1_id: self.s1, self.p2_id: self.s2}
        score1 = score_map.get(entrant1_id, 0)
        score2 = score_map.get(entrant2_id, 0)

        if score1 > score2:
            winner_id = entrant1_id
        elif score2 > score1:
            winner_id = entrant2_id
        else:
            await inter.response.send_message("スコアが未入力、または引き分けです。", ephemeral=True)
            return

        gameData = []
        for _ in range(score1):
            gameData.append({"winnerId": entrant1_id, "entrant1Score": 1, "entrant2Score": 0})
        for _ in range(score2):
            gameData.append({"winnerId": entrant2_id, "entrant1Score": 0, "entrant2Score": 1})
        for i, g in enumerate(gameData, start=1):
            g["gameNum"] = i

        payload = {"setId": int(self.set_id), "winnerId": winner_id, "gameData": gameData}

        await inter.response.defer(ephemeral=True)
        try:
            await gql_async(MUT_REPORT_SET, payload)
        except Exception:
            await inter.followup.send("すでにスタッフによって処理されています。", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True
        embed = inter.message.embeds[0].copy()
        embed.description = "✅ **この試合は終了しました**\n\n" + embed.description
        await inter.message.edit(embed=embed, view=self)
        await inter.followup.send("スコアを送信しました。", ephemeral=True)

        active_views.pop(self.set_id, None)
        completed_set_ids.add(self.set_id)


class ScoreBtn(discord.ui.Button):
    def __init__(self, player: int, score: int, row: int):
        super().__init__(label=str(score), style=discord.ButtonStyle.secondary, custom_id=f"s{player}_{score}", row=row)
        self.player = player
        self.score = score

    async def callback(self, inter: discord.Interaction):
        view: ReportButtons = self.view  # type: ignore
        await view.update_score(inter, self.player, self.score, self)


class OkBtn(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="OK", style=discord.ButtonStyle.success, custom_id="ok", row=row)

    async def callback(self, inter: discord.Interaction):
        view: ReportButtons = self.view
        await view.send(inter)

async def post_announce(set_node: dict, station: str):
    set_id = set_node.get("id")
    slots = set_node.get("slots", [])

    if len(slots) < 2 or not all(slot.get("entrant") for slot in slots):
        logger.warning(f"対戦者が揃っていないためスキップ: set_id={set_id}")
        return

    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        logger.error("チャンネルが取得できません")
        return

    try:
        p1_part = slots[0]["entrant"]["participants"][0]
        p2_part = slots[1]["entrant"]["participants"][0]
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"スロット情報が不完全: {e}")
        return

    mention1 = mention(p1_part)
    mention2 = mention(p2_part)
    mention_line = f"📢 {mention1} {mention2}"

    round_text = f"🏷️ {set_node.get('fullRoundText', '不明なラウンド')}"
    try:
        station_i = int(station)
    except (TypeError, ValueError):
        station_i = 9999
    if station_i == 1:
        station_text = "🖥️ **Station 1** 🎥**配信台**"
    elif station_i <= STREAM_NUMBER:
        station_text = f"🖥️ **Station {station_i}** 🎥**サブ配信台**"
    else:
        station_text = f"🖥️ **Station {station_i}**"
    station_text = "🖥️ **Station 1** 🎥**配信台**" if str(station) == "1" else f"🖥️ **Station {station}** 🎥**サブ配信台**" if int(station) <= STREAM_NUMBER else f"🖥️ **Station {station}**"

    team1 = slots[0]["entrant"]["name"]
    team2 = slots[1]["entrant"]["name"]
    if len(slots[0]["entrant"]["participants"]) == 1 and len(slots[1]["entrant"]["participants"]) == 1:
        content = f"{round_text}\n\n{station_text}\n\n{mention1} (0)\nvs\n{mention2} (0)"
    else:
        content = f"{round_text}\n\n{station_text}\n\n{team1} (0)\nvs\n{team2} (0)"

    view = ReportButtons(set_id=set_id, p1_id=slots[0]["entrant"]["id"], p2_id=slots[1]["entrant"]["id"])

    old_view = active_views.get(set_id)
    if old_view and old_view.get("message"):
        message = old_view["message"]
        embed = message.embeds[0].copy()
        lines = embed.description.splitlines()
        lines[2] = station_text
        embed.description = "\n".join(lines)
        await message.edit(embed=embed, view=view)
        bot.add_view(view)
        active_views[set_id]["view"] = view
    else:
        message = await channel.send(
            content=mention_line,
            embed=discord.Embed(description=content, color=discord.Color.blue()),
            view=view,
            allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True),
        )
        bot.add_view(view)
        active_views[set_id] = {"view": view, "slots": slots, "message": message}

_last_poll_timestamp: int = 0

@tasks.loop(seconds=POLL_INTERVAL)
async def poll_sets():
    global initial_scan_done, _last_poll_timestamp
    await bot.wait_until_ready()

    # 初回スキャン
    if not initial_scan_done:
        page = 1
        while True:
            try:
                data = await gql_async(QUERY_ALL_SETS, {"slug": TOURNAMENT_SLUG, "page": page})
            except Exception as e:
                logger.error(f"GraphQL error (initial scan): {e}")
                return
            if "data" not in data:
                logger.error(f"GraphQL data missing: {data.get('errors')}")
                return

            sets = [
                s for ev in data["data"]["tournament"]["events"]
                for s in ev["sets"]["nodes"] if s and s.get("station")
            ]
            if not sets:
                break

            for s in sets:
                set_id = s["id"]
                station_map[set_id] = s["station"]["number"]
                if s.get("state") == 3:
                    completed_set_ids.add(set_id)
            page += 1

        initial_scan_done = True
        _last_poll_timestamp = int(time.time())
        logger.info(f"Initial scan done: {len(station_map)} sets tracked, {len(completed_set_ids)} already completed")
        return

    active_sets = []
    page = 1
    while True:
        try:
            data = await gql_async(QUERY_ACTIVE_SETS, {"slug": TOURNAMENT_SLUG, "page": page})
        except Exception as e:
            logger.error(f"GraphQL error (active sets): {e}")
            return
        if "data" not in data:
            logger.error(f"GraphQL data missing (active): {data.get('errors')}")
            return

        page_sets = [
            s for ev in data["data"]["tournament"]["events"]
            for s in ev["sets"]["nodes"] if s
        ]
        if not page_sets:
            break
        active_sets.extend(s for s in page_sets if s.get("station"))
        if len(page_sets) < 50:
            break
        page += 1
    for s in active_sets:
        station = s["station"]["number"]
        set_id = s["id"]
        if station_map.get(set_id) != station:
            station_map[set_id] = station
            await post_announce(s, station)

    # active_views にあるが今回のポーリング結果に含まれないセット = Web側で完了済み
    active_set_ids = {s["id"] for s in active_sets}
    disappeared = [sid for sid in list(active_views.keys()) if sid not in active_set_ids and sid not in completed_set_ids]
    for sid in disappeared:
        view_info = active_views.get(sid)
        if not view_info:
            continue
        message = view_info.get("message")
        view = view_info.get("view")
        if not message or not view:
            active_views.pop(sid, None)
            completed_set_ids.add(sid)
            continue
        try:
            embed = message.embeds[0].copy()
            embed.description = "✅ **この試合は終了しました\n（スタッフにより処理されました）**\n\n" + embed.description
            for item in view.children:
                item.disabled = True
            await message.edit(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to update disappeared set UI: {sid}: {e}")
        active_views.pop(sid, None)
        completed_set_ids.add(sid)

    # 完了セット差分取得 (残枠が少なければスキップし mutation を優先)
    if rate_limiter.remaining < 10:
        logger.debug("Skipping completed-set check (preserving rate limit budget)")
    else:
        try:
            data = await gql_async(QUERY_COMPLETED_SETS, {
                "slug": TOURNAMENT_SLUG,
                "page": 1,
                "updatedAfter": _last_poll_timestamp,
            })
        except Exception as e:
            logger.error(f"GraphQL error (completed sets): {e}")
            _last_poll_timestamp = int(time.time())
            return

        if "data" in data:
            for s in [
                s for ev in data["data"]["tournament"]["events"]
                for s in ev["sets"]["nodes"] if s
            ]:
                set_id = s["id"]
                if set_id in completed_set_ids:
                    continue
                completed_set_ids.add(set_id)
                await update_finished_match_ui(s)

    _last_poll_timestamp = int(time.time())

@bot.tree.command(name="assign_roles", description="大会参加者にロールを付与")
@app_commands.describe(role="付与するロール")
async def assign_roles(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(thinking=True)
    user_pairs = await fetch_discord_ids_from_startgg()
    guild = interaction.guild

    assigned = []
    failed = []
    for uid, gamerTag in user_pairs:
        member = guild.get_member(uid)
        if member is None:
            try:
                member = await guild.fetch_member(uid)
            except discord.NotFound:
                failed.append((gamerTag, "NotFound"))
                continue
            except discord.HTTPException as e:
                failed.append((gamerTag, f"HTTPError: {e}"))
                continue
        try:
            await member.add_roles(role, reason="start.gg上の参加者にロール付与")
            assigned.append(gamerTag)
        except Exception as e:
            failed.append((gamerTag, f"RoleError: {e}"))

    msg = format_result_message("付与", "に", assigned, role)
    if failed:
        msg += f"\n\n⚠️ ロール付与に失敗した参加者 {len(failed)}名:\n" + "\n".join(f"- {g} ({reason})" for g, reason in failed)
    await interaction.followup.send(msg)


@bot.tree.command(name="remove_roles", description="大会参加者からロールを削除")
@app_commands.describe(role="削除するロール")
async def remove_roles(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(thinking=True)
    user_pairs = await fetch_discord_ids_from_startgg()
    guild = interaction.guild

    removed = []
    for uid, gamerTag in user_pairs:
        member = guild.get_member(uid)
        if member:
            try:
                await member.remove_roles(role, reason="start.gg参加者からロール削除")
                removed.append(gamerTag)
            except Exception:
                pass

    msg = format_result_message("削除", "から", removed, role)
    await interaction.followup.send(msg)

async def setup_hook():
    bot.add_view(FallbackReportView())

bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    logger.info(f"Notification channel = {DISCORD_CHANNEL_ID}")
    poll_sets.start()
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
