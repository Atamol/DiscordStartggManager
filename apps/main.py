import os
import asyncio
import json
import re
import requests
import functools
from typing import Optional

import discord
from discord.ext import tasks, commands
from discord import app_commands

DISCORD_BOT_TOKEN   = os.getenv("DISCORD_BOT_TOKEN")
STARTGG_API_TOKEN   = os.getenv("STARTGG_API_TOKEN")
DISCORD_CHANNEL_ID  = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
TOURNAMENT_SLUG     = os.getenv("TOURNAMENT_SLUG")

GQL_ENDPOINT        = "https://api.start.gg/gql/alpha"
POLL_INTERVAL       = 2

initial_scan_done = False
station_map: dict[str, str] = {}
active_views: dict[str, dict] = {}  # {set_id: {view, slots}}

# GraphQL: 参加者の取得
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

# GraphQ: 対戦情報などの取得
QUERY_SETS = """
query GetSets($slug: String!, $page: Int!) {
  tournament(slug: $slug) {
    events {
      sets(page: $page, perPage: 50, sortType: STANDARD) {
        nodes {
          id
          fullRoundText
          state
          station { number }
          slots {
            entrant {
              id
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
  }
}
"""

# GraphQ: 対戦結果の報告
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

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=";", intents=intents)

# GraphQLとの通信
def gql_sync(query: str, variables: dict):
    headers = {
        "Authorization": f"Bearer {STARTGG_API_TOKEN}",
        "Content-Type": "application/json",
    }
    resp = requests.post(GQL_ENDPOINT, json={"query": query, "variables": variables}, headers=headers, timeout=15)
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(json.dumps(data["errors"], indent=2, ensure_ascii=False))
    return data

async def gql_async(query: str, variables: dict, timeout_sec: int = 10):
    loop = asyncio.get_running_loop()
    fn = functools.partial(gql_sync, query, variables)
    return await asyncio.wait_for(loop.run_in_executor(None, fn), timeout=timeout_sec)

# メンション
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

# Discord UI
class ReportButtons(discord.ui.View):
    def __init__(self, set_id: str, p1_id: int, p2_id: int):
        super().__init__(timeout=None)
        self.set_id = set_id
        self.p1_id = p1_id
        self.p2_id = p2_id
        self.s1: Optional[int] = 0
        self.s2: Optional[int] = 0

        # プレイヤー1（上段）
        for s in range(4):  # 0,1,2,3
            self.add_item(ScoreBtn(1, s, row=0))

        # プレイヤー2（下段）
        for s in range(4):  # 0,1,2,3
            self.add_item(ScoreBtn(2, s, row=1))

        # OK
        self.add_item(OkBtn(row=2))

    # スコア反映
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

    # スコア送信
    async def send(self, inter: discord.Interaction):
        if self.s1 == self.s2:
            await inter.response.send_message("スコアが同点です。", ephemeral=True)
            return

        slots = active_views[self.set_id]["slots"]
        entrant1_id = slots[0]["entrant"]["id"]
        entrant2_id = slots[1]["entrant"]["id"]

        score_map = {
            self.p1_id: self.s1,
            self.p2_id: self.s2
        }

        score1 = score_map.get(entrant1_id, 0)
        score2 = score_map.get(entrant2_id, 0)

        if score1 > score2:
            winner_id = entrant1_id
        elif score2 > score1:
            winner_id = entrant2_id
        else:
            await inter.response.send_message("スコアが未入力、または引き分けです。", ephemeral=True)
            return

        # gameDataを構築
        gameData = []

        for _ in range(score1):
            gameData.append({
                "winnerId": entrant1_id,
                "entrant1Score": 1,
                "entrant2Score": 0
            })

        for _ in range(score2):
            gameData.append({
                "winnerId": entrant2_id,
                "entrant1Score": 0,
                "entrant2Score": 1
            })

        for i, g in enumerate(gameData, start=1):
            g["gameNum"] = i

        payload = {
            "setId": int(self.set_id),
            "winnerId": winner_id,
            "gameData": gameData
        }

        try:
            await gql_async(MUT_REPORT_SET, payload)
        except Exception as e:
            await inter.response.send_message(f"start.ggへの送信に失敗しました: {e}", ephemeral=True)
            return

        self.disable_all_items()
        embed = inter.message.embeds[0].copy()
        embed.description = "✅ **この試合は終了しました**\n\n" + embed.description
        await inter.message.edit(embed=embed, view=self)
        await inter.response.send_message("スコアを送信しました。", ephemeral=True)

    # 受付終了
    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

# スコア入力ボタン
class ScoreBtn(discord.ui.Button):
    def __init__(self, player: int, score: int, row: int):
        super().__init__(
            label=str(score),
            style=discord.ButtonStyle.secondary,
            custom_id=f"s{player}_{score}",
            row=row
        )
        self.player = player
        self.score = score

    async def callback(self, inter: discord.Interaction):
        view: ReportButtons = self.view  # type: ignore
        await view.update_score(inter, self.player, self.score, self)

# スコア送信ボタン
class OkBtn(discord.ui.Button):
    def __init__(self, row: int):
        super().__init__(label="OK", style=discord.ButtonStyle.success, custom_id="ok", row=row)

    async def callback(self, inter: discord.Interaction):
        view: ReportButtons = self.view
        await view.send(inter)

# 通知処理
async def post_announce(set_node: dict, station: str):
    slots = set_node.get("slots", [])
    set_id = set_node.get("id")

    # プレイヤーが2人揃っていない場合はスキップ
    if len(slots) < 2 or not all(slot.get("entrant") for slot in slots):
        print(f"[WARNING] 対戦者が揃っていないためスキップ: set_id = {set_id}")
        return

    # チャンネル取得
    channel = bot.get_channel(DISCORD_CHANNEL_ID)
    if not channel:
        print("[ERROR] チャンネルが取得できません。")
        return

    try:
        p1_part = slots[0]["entrant"]["participants"][0]
        p2_part = slots[1]["entrant"]["participants"][0]
    except (KeyError, IndexError, TypeError) as e:
        print(f"[WARNING] スロット情報が不完全です: {e}")
        return

    # 旧メッセージがあれば削除
    old_msg = active_views.get(set_id, {}).get("message")
    if old_msg:
        try:
            await old_msg.delete()
            print(f"[INFO] 古いメッセージを削除: set_id = {set_id}")
        except Exception as e:
            print(f"[WARNING] メッセージ削除失敗: {e}")

    # メンションの取得
    mention1 = mention(p1_part)
    mention2 = mention(p2_part)

    # Contentフォーマット
    mention_line = f"📢 {mention1} {mention2}"

    # Stationフォーマット
    if str(station) == "1":
        station_text = "🖥️ **Station 1** 🎥**配信台**"
    else:
        station_text = f"🖥️ **Station {station}**"

    # Descriptionフォーマット
    round_text = f"🏷️ {set_node.get('fullRoundText', '不明なラウンド')}"
    content = f"{round_text}\n\n{station_text}\n\n{mention1} (0)\nvs\n{mention2} (0)"

    # ビューの生成と送信
    view = ReportButtons(
        set_id=set_id,
        p1_id=slots[0]["entrant"]["id"],
        p2_id=slots[1]["entrant"]["id"]
    )

    message = await channel.send(
        content=mention_line,
        embed=discord.Embed(description=content, color=discord.Color.blue()),
        view=view,
        allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True)
    )

    bot.add_view(view)
    active_views[set_id] = {
        "view": view,
        "slots": slots,
        "message": message  # メッセージを保存し，再アサイン時に削除
    }

# ポーリング処理
@tasks.loop(seconds=POLL_INTERVAL)
async def poll_sets():
    global initial_scan_done
    await bot.wait_until_ready()
    page = 1
    while True:
        try:
            data = await gql_async(QUERY_SETS, {"slug": TOURNAMENT_SLUG, "page": page})
        except Exception as e:
            print("GraphQL error:", e)
            return

        if "data" not in data:
            print("GraphQL: data missing", data.get("errors"))
            return

        sets = [
            s for ev in data["data"]["tournament"]["events"]
            for s in ev["sets"]["nodes"] if s and s.get("station")
        ]

        if not sets:
            initial_scan_done = True
            break

        for s in sets:
            station = s["station"]["number"]
            set_id = s["id"]

            if not initial_scan_done:
                station_map[set_id] = station
                continue

            if station_map.get(set_id) != station:
                station_map[set_id] = station
                await post_announce(s, station)

        page += 1

# Discord IDの取得
async def fetch_discord_ids_from_startgg() -> list[tuple[int, str]]:
    data = await gql_async(GET_PARTICIPANTS_QUERY, { "slug": TOURNAMENT_SLUG })
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

# ロール付与コマンドのフォーマット統一用
def format_result_message(action: str, preposition: str, members: list[str], role: discord.Role) -> str:
    if not members:
        return f"⚠️ 該当ユーザーが見つかりませんでした。"

    return f"✅ 以下の {len(members)}名 {preposition}ロール `{role.name}` を{action}しました:\n\n" + \
           "\n".join(f"- {m}" for m in members)

# ロール付与
@bot.tree.command(name="assign_roles", description="大会参加者にロールを付与")
@app_commands.describe(role="付与するロール")
async def assign_roles(interaction: discord.Interaction, role: discord.Role):
    await interaction.response.defer(thinking=True)
    user_pairs = await fetch_discord_ids_from_startgg()
    guild = interaction.guild

    assigned = []
    for uid, gamerTag in user_pairs:
        member = guild.get_member(uid)
        if member:
            try:
                await member.add_roles(role, reason="start.gg上の参加者にロール付与")
                assigned.append(gamerTag)
            except Exception:
                pass

    msg = format_result_message("付与", "に", assigned, role)
    await interaction.followup.send(msg)

# ロール削除
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

# 起動処理
@bot.event
async def on_ready():
    await bot.wait_until_ready()
    try:
        synced = await bot.tree.sync()
        print(f"✅ スラッシュコマンドを {len(synced)} 個を同期しました。")
    except Exception as e:
        print(f"[ERROR] スラッシュコマンドの同期に失敗: {e}")

    poll_sets.start()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

if __name__ == "__main__":
    bot.run(DISCORD_BOT_TOKEN)
