# DEMO

https://github.com/user-attachments/assets/fd001337-2c11-4234-ad85-2ae82752e80b

# DiscordStartggManager

DiscordStartggManager は，Discord 上で start.gg トーナメントの試合進行をスムーズにサポートするための Bot です．

| 機能 | 説明 |
| --- | --- |
| 🎮 試合通知機能	| start.gg上で対戦台が設定されると，Discordにメンション付き対戦カードを送信します |
| 🔘 スコア入力機能	| Discord上で，ボタンからスコアの入力ができます |
| ✅ 勝敗確定・完了表示	| スコアを送信すると終了済みマッチとしてマークされ，受付が締め切られます |
| 🖥️ 対戦台の再登録にも対応	| 台番号が変更された場合，Discordの投稿が自動的に編集されます |
| 👥 参加者へのロール付与	| 参加者全員に対してロールの付与・削除が可能です（`@everyone`による不参加者へのメンションの防止） |

# 導入方法

### ❗ 現在，このBotは開発者自身によりホスティングされていません

現在，このBotを利用するには，利用者の環境でこのBotをホスティングしていただく必要があります．

> 将来的に，Webから簡単に設定を行えるようにしたり，大型大会での運用もできるように最適化させることが目標に開発を勧めています．協力者を募集しています！

導入が難しい場合は個別のサポートを行っているので，[X (Twitter)](https://x.com/Atamol_ssb)からお気軽にご相談ください．

## 1. Dockerを使う方法

1. このリポジトリをクローンします．
2. [Diescord Developer Portal](https://discord.com/developers/applications)から，DiscordのBotを作成し，権限の設定を行います．
3. 作成したBotを運用したいDiscordへ招待します．
4. `.env`に，必要な情報を設定します．
5. Dockerコンテナをビルドします．
6. コンテナを実行します．

## 2. ターミナルから起動する方法

1. このリポジトリをクローンします．
2. [Diescord Developer Portal](https://discord.com/developers/applications)から，DiscordのBotを作成し，権限の設定を行います．
3. 作成したBotを運用したいDiscordへ招待します．
4. `.env`に，必要な情報を設定します．
5. 13・14行目の`from dotenv import load_dotenv`，`load_dotenv()`のコメントアウトを外します．
6. `apps/main.py`を実行します．

# ❗ 協力者を募集しています
このプロジェクトは，一般公開に向けて個人で地道に開発を進めています．  
将来的に，Webから簡単に設定を行えるようにしたり，大型大会での運用もできるように最適化させることが目標です．
バグ報告や機能追加の提案など，どのような形でもご協力いただけると嬉しいです．  
開発者からのプルリクエストも歓迎しております．
