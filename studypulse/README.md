# StudyPulse

A voice-first spaced-repetition study coach, built as an MCP server
(Streamable HTTP) for Alexa+. The student adds flashcards by talking, gets
quizzed on exactly the cards they are about to forget, and gets a weekly
review of accuracy and weak topics.

## Tools

| Tool | What it does |
|------|--------------|
| `add_card(topic, question, answer)` | Save a flashcard, due immediately |
| `quiz_me(topic?)` | Next due card (most overdue, hardest first) |
| `log_result(card_id, quality 0-5)` | Grade the answer, schedule next review (SM-2) |
| `list_topics()` | Topics with card counts and how many are due |
| `weekly_review()` | 7-day reviews, accuracy, active days, weakest topics |

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q          # unit tests
python server.py             # serves http://127.0.0.1:8000/mcp
python smoke.py              # in a 2nd terminal: calls every tool over HTTP
```

Environment variables: `HOST`, `PORT`, `STUDYPULSE_DB` (SQLite file path).

## Web app: chat page + MCP endpoint in one process

```bash
python app.py     # http://127.0.0.1:8000/  (chat)   and   /mcp  (MCP server)
```

| Variable | Purpose |
|----------|---------|
| `BEDROCK_MODEL_ID` | Bedrock model or inference-profile ID (copy it from the Bedrock console) |
| `AWS_REGION` | Region where you enabled that model (default `us-east-1`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Credentials. Never commit these. |
| `STUDYPULSE_STUB_LLM=1` | Offline stand-in for Bedrock, to try the UI with no AWS account |

The chat page uses the browser's built-in speech recognition and speech
synthesis (Chrome or Edge recommended) to give a voice-first experience.

## Deploy

Build command `pip install -r requirements.txt`, start command `python app.py`,
with `HOST=0.0.0.0`, `PORT` (most hosts set this for you) and the AWS variables
above. Free hosting tiers often reset the disk on restart, which wipes the
SQLite file: fine for a demo, not for real students.

Set an AWS Budgets alert before sharing the public link. Anyone who opens the
page can trigger model calls on your account.

## How it works

- `scheduler.py`: pure SM-2 algorithm (no I/O, fully unit-tested)
- `db.py`: SQLite storage, standard library only
- `server.py`: MCP tool definitions and input validation

## Known limits

- Single student per database (no user accounts yet).
- Due dates use the server's date, so a server in UTC can be off by up to a
  day for a student in another timezone.
