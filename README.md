# AURA Backend API

Flask API that wraps the AURA legal-literacy chatbot (Gemini + crisis
detection + 75-entry legal reference database) so it can be called from a
website chat widget. Your `GEMINI_API_KEY` stays on the server — it is never
sent to the browser.

## Files

- `app.py` — the Flask API (routes: `/chat`, `/health`, `/session/<id>`)
- `legal_database.py` — all 75 legal scenarios (30 original + 45 from the PDF)
- `requirements.txt` — Python dependencies

## Run locally

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-key-here"
python app.py
```

Test it:

```bash
curl -X POST http://localhost:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "My landlord won'"'"'t return my deposit"}'
```

You should get back JSON with a `reply`, a `session_id` (save this and send
it on every later message so AURA remembers the conversation), and `crisis`
(null unless a high-risk phrase was detected).

## Deploy (Render — free tier friendly)

1. Push this folder to a GitHub repo (or a folder within your existing repo).
2. Go to https://render.com → New → Web Service → connect the repo.
3. Settings:
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
4. Add an environment variable: `GEMINI_API_KEY` = your actual key.
5. Deploy. Render gives you a URL like `https://aura-api.onrender.com`.
6. Update the CORS line in `app.py` to your real site domain instead of `"*"`
   before going live:
   ```python
   CORS(app, origins=["https://your-actual-site.lovable.app"])
   ```

Railway and Fly.io work the same way — push the repo, set the
`GEMINI_API_KEY` env var, set the start command to `gunicorn app:app`.

## API reference

### POST /chat
Request:
```json
{ "message": "My phone got stolen in the metro", "session_id": "optional-existing-id" }
```
Response:
```json
{
  "reply": "I'm sorry that happened. Here's what you can do...",
  "session_id": "generated-or-passed-through-id",
  "crisis": null,
  "matched_scenario_id": "SC-01"
}
```
If a crisis phrase is detected, `crisis` will instead look like:
```json
{ "category": "domestic_abuse", "message": "Please know you're not alone..." }
```
The frontend should always display `reply` normally, and if `crisis` is not
null, show its `message` prominently (e.g. a highlighted banner above the
reply) rather than replacing the reply.

### GET /health
Returns `{"status": "ok", "database_entries": 75}` — useful for uptime checks.

### DELETE /session/<session_id>
Clears a stored conversation (e.g. when the user clicks "clear chat").

## Known limitations to address before real production use

- **Sessions are in-memory** (`_sessions` dict in `app.py`). They reset on
  server restart and won't work if you scale to multiple server instances.
  Fine for a single small Render/Railway instance; move to Redis if you
  outgrow that.
- **No rate limiting.** Anyone with your API URL could send unlimited
  requests, which costs you Gemini API usage. Consider adding a simple
  per-IP rate limit (e.g. `flask-limiter`) before wide release.
- **CORS is wide open (`origins="*"`).** Lock this to your real domain
  before launch.
- This is general legal information, not legal advice — keep that
  disclaimer visible in the chat UI itself, not just in this README.
