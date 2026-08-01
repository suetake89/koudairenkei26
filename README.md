# 勉強計画モデル可視化アプリ

勉強計画の数理最適化モデルを、画面上で操作しながら確認するための Streamlit アプリです。

## まずアプリを見る

公開版のリンク：

[https://koudairenkei26.streamlit.app/](https://koudairenkei26.streamlit.app/)

リンクが開ける場合は、インストール作業は不要です。ブラウザだけで利用できます。

※ リンクが切れる可能性があります。切れた場合は、自分でデプロイするか、自分のPCで実行して生徒に操作させてください。

## リンクが開けない場合

公開リンクが切れている、またはネットワークの都合で開けない場合は、自分でデプロイするか、自分のPCにコピーして実行します。

必要なものは次の3つです。

- Git
- Python
- uv または pip

## GitHubを初めて使う人向け

### 1. Gitをインストールする

macOS の場合、ターミナルで次を実行します。

```bash
git --version
```

もし Git が入っていなければ、案内に従って Command Line Tools をインストールしてください。

Windows の場合は、以下から Git for Windows をインストールします。

```text
https://git-scm.com/download/win
```

インストール後、ターミナルまたは PowerShell で確認します。

```bash
git --version
```

### 2. このリポジトリをcloneする

作業したいフォルダに移動して、次を実行します。

```bash
git clone https://github.com/suetake89/koudairenkei26.git
cd koudairenkei26
```

これで、アプリのファイルが自分のPCにコピーされます。

## uvで実行する方法

uv が入っている場合は、これが一番簡単です。

```bash
uv sync
uv run streamlit run app.py
```

ブラウザで次のようなURLが開きます。

```text
http://localhost:8501
```

もし 8501 が使用中と言われたら、別のポートで起動します。

```bash
uv run streamlit run app.py --server.port 8502
```

## uvがない場合：pipで実行する方法

uv が入っていない場合は、Python の仮想環境と pip を使います。

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## アプリでできること

- 勉強単位を選ぶ
  - 1時間
  - 30分
  - 20分
  - 15分
  - 10分
  - 5分
- 固定予定を設定する
- 勉強・休憩を最適化する
- 勉強時間の下限・上限を設定する
- モチベーション変化を入れる
- 7日間の計画に広げる
- 科目と科目別最低時間を入れる
- 現在のモデルの数式を確認する

## 補足

Streamlit アプリ本体は `app.py` です。

## 固定時間をSupabaseへ保存する

固定時間は `day`（7日間化OFF）と `week`（7日間化ON）ごとに、次の5設定を保存できます。

- 部活なし
- 部活あり
- デフォルト３
- デフォルト４
- デフォルト５

1. Supabaseでプロジェクトを作成します。
2. SQL Editorで `supabase_schema.sql` を実行します。
3. `.streamlit/secrets.toml.example` を `.streamlit/secrets.toml` としてコピーし、SupabaseのProject URLとSecret key（`sb_secret_...`）を設定します。
4. Streamlit Community Cloudでは、アプリのSettings → Secretsに同じ内容を登録します。

Secret keyはサーバー専用の秘密情報です。GitHubへコミットしたり、ブラウザ側へ渡したりしないでください。保存済み設定は、アプリ起動時や設定切替時にDBから自動で読み込まれます。固定時間をまとめてチェックして「変更をまとめて反映」を押してから、「この設定をDBへ保存」を操作します。旧`service_role` keyにも対応しています。

### cloneした全員で同じDBを使う場合

`supabase_public.json` にProject URLとPublishable key（`sb_publishable_...`）を設定してGitHubへコミットします。Publishable keyは公開可能ですが、`supabase_schema.sql`の匿名RLS設定により、誰でも固定時間を読み込み・上書きできる運用になります。行の削除権限はありません。

ローカルの`.streamlit/secrets.toml`が存在する場合は、そちらの接続情報を優先します。Secret keyは引き続きGitHubへコミットしないでください。
