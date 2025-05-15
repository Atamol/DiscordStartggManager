# How to Use & How it Works

https://github.com/user-attachments/assets/fd001337-2c11-4234-ad85-2ae82752e80b

# DiscordStartggManager

DiscordStartggManager は，Discord 上で start.gg トーナメントの試合進行をスムーズにサポートするための BOT です．

| 機能 | 説明 |
| --- | --- |
| 🎮 試合通知機能	| start.gg 上で対戦台が設定されると，Discord に自動でカードを送信します |
| 🔘 スコア入力機能	| Discord 上で，ボタンからスコアの入力ができます |
| ✅ 勝敗確定・完了表示	| スコアを送信すると，試合が終了としてマークされ，受付が締め切られます |
| 🖥️ 対戦台の再登録にも対応	| 台番号が変更された場合，Discordの投稿が自動的に編集されます |
| 👥 参加者へのロール付与	| トナメ参加者に対して自動的にロールを付与・削除できます（`@everyone`による不参加者へのメンションを防げます） |

# 導入方法

### ❗ 現在，このBotは開発者自身によりホスティングされていません

そのため，利用者の環境でBotをホスティングしていただく必要があります（かなり先の話になりますが，今後はBotを招待するだけで使用できるようにする予定です）．
導入が難しい場合は，VCなどを用いたサポートを行っているので，[X (Twitter)](https://x.com/Atamol_ssb) からお気軽にご相談ください．

1. このリポジトリをクローンします．
2. [Diescord Developer Portal](https://discord.com/developers/applications)から，DiscordのBotを作成し，運用したいサーバーへ招待します（招待に当たり権限の設定などが必要となるため，初めての方は調べながら行ってください）．
3. Pythonをインストールします．
4. `requirements.txt`をインストールします．
5. `.env`に，必要な情報を設定します．
