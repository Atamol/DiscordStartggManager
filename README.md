## [English ver. here](https://github.com/Atamol/DiscordStartggManager/blob/main/README-EN.md)

#  [公式Discord](https://discord.gg/VtWxvdXz5H)

# DiscordStartggManager

**DiscordStartggManager** は，Discord 上で start.gg トーナメントの試合進行をスムーズにサポートするための Bot です．
主に**大乱闘スマッシュブラザーズシリーズ**を想定して作られています．


<video src="./docs/demo_vid_2025-04-24.mp4" controls width="100%"></video>

# 導入方法

### ❗ 現在，このBotは開発者自身によりホスティングされていません

現在，このBotを利用するには，利用者の環境でこのBotをホスティングしていただく必要があります．

> もっと簡単に使っていただけるよう，がんばって開発を勧めています．協力者を募集しています！

導入が難しい場合は個別のサポートを行っているので，[公式Discord](https://discord.gg/VtWxvdXz5H)からお気軽にご相談ください．

## 1. Dockerを使う方法

1. このリポジトリをクローンします．
2. [Diescord Developer Portal](https://discord.com/developers/applications)から，DiscordのBotを作成し，権限の設定を行います．
3. 作成したBotを運用したいDiscordへ招待します．
4. `.env`に，必要な情報を設定します．
5. `from dotenv import load_dotenv`，`load_dotenv()`をコメントアウトします．
6. Dockerコンテナをビルドします．
7. コンテナを実行します．

## 2. ターミナルから起動する方法

1. このリポジトリをクローンします．
2. [Diescord Developer Portal](https://discord.com/developers/applications)から，DiscordのBotを作成し，権限の設定を行います．
3. 作成したBotを運用したいDiscordへ招待します．
4. `.env`に，必要な情報を設定します．
5. `main.py`を実行します．

# ❗ 協力者を募集しています

このプロジェクトは，一般公開に向けて個人で地道に開発を進めています．

→ [公式Discord](https://discord.gg/VtWxvdXz5H)

将来的に，Webから簡単に設定を行えるようにしたり，大型大会での運用もできるように最適化させることが目標です．
バグ報告や機能追加の提案など，どのような形でもご協力いただけると嬉しいです．
開発者からのプルリクエストも歓迎しております．
