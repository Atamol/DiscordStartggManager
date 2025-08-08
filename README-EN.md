[日本語 / Japanese Ver.](https://github.com/Atamol/DiscordStartggManager/blob/main/README.md)

Translated by OpenAI.

# DEMO

https://github.com/user-attachments/assets/fd001337-2c11-4234-ad85-2ae82752e80b

# DiscordStartggManager

**DiscordStartggManager** is a Discord bot designed to make running tournaments on [start.gg](https://start.gg/) smoother and more efficient.  
This project’s made with the Super Smash Bros. series in mind.

| Feature | Description |
| --- | --- |
| 🎮 Match Notifications | When a match station is assigned on start.gg, the bot sends a mention-tagged match card in Discord. |
| 🔘 Score Input | Allows you to submit match scores directly from Discord using buttons. |
| ✅ Match Completion | Once scores are submitted, the match is marked as complete and locked from further edits. |
| 🖥️ Supports Reassignment | If a station number changes, the bot automatically updates the existing post in Discord. |
| 👥 Role Assignment for Participants | Quickly add or remove a role for all participants (helps avoid pinging non-participants with `@everyone`). |

# How to Set It Up

### ❗ Currently, this bot is **not** hosted by the developer

If you want to use it right now, you’ll need to host it yourself.  

> I’m working on making it easier to set up and use — and I’m looking for collaborators to help improve it!  

If hosting it yourself sounds tricky, I also offer one-on-one setup support. Feel free to reach out via [X (Twitter)](https://x.com/Atamol_ssb).

## 1. Using Docker

1. Clone this repository.  
2. Go to the [Discord Developer Portal](https://discord.com/developers/applications), create a bot, and set its permissions.  
3. Invite the bot to your target Discord server.  
4. Fill in the required information in the `.env` file.  
5. Comment out lines 13 and 14: `from dotenv import load_dotenv` and `load_dotenv()`.  
6. Build the Docker container.  
7. Run the container.  

## 2. Running from Terminal

1. Clone this repository.  
2. Go to the [Discord Developer Portal](https://discord.com/developers/applications), create a bot, and set its permissions.  
3. Invite the bot to your target Discord server.  
4. Fill in the required information in the `.env` file.  
5. Run `apps/main.py`.  

# ❗ Looking for Collaborators
This project is being developed solo, step-by-step, with the goal of making it ready for public use.  
Future plans include adding a web-based setup interface and optimizing it for large-scale tournament operations.  
Bug reports, feature suggestions, and any other kind of contribution are welcome!  
Pull requests from developers are also greatly appreciated.  