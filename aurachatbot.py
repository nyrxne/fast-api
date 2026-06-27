"""AURA Legal Literacy Chatbot — FastAPI backend."""
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from google import genai

from legal_database import LEGAL_DATABASE
api_key = GEMINI_API_KEY
if not api_key:
    raise EnvironmentError(
        "GEMINI_API_KEY environment variable not set. "
        "Set it in your deployment platform's environment variables, "
        "or locally: export GEMINI_API_KEY='your-key-here'"
    )

client = genai.Client(api_key=api_key)

SYSTEM_PROMPT = """You are AURA, a conversational legal literacy assistant.
Help users understand rights, safety, and practical next steps.
Explain legal ideas in plain language.
Speak naturally and empathetically like a helpful friend.
Be conversational, practical, and supportive.
Avoid sounding robotic, overly formal, or textbook-like.
Avoid constantly referring users to documentation.
Do NOT pretend to be a lawyer.
Do NOT provide definitive legal advice.
Encourage professional help for serious legal emergencies.
Ask clarifying questions when jurisdiction matters.
Use examples when useful.
Keep responses concise but useful.
If unsure, clearly say so instead of hallucinating.
Be friendly, approachable, and non-judgmental. Human and clear above all."""
_sessions: dict[str, "genai.chats.Chat"] = {}


def get_or_create_chat(session_id: str):
    """Return the existing chat session, or create a new one."""
    if session_id not in _sessions:
        _sessions[session_id] = client.chats.create(
            model="gemini-2.5-flash-lite",
            config=genai.types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT
            ),
        )
    return _sessions[session_id]
HIGH_RISK_KEYWORDS = {
    "self_harm": [
        "suicide", "self-harm", "hurt myself", "kill myself",
        "end my life", "want to disappear",
    ],
    "violence": [
        "murder", "kill", "assault", "violent", "threat",
        "weapon", "stabbing", "beating", "shooting",
    ],
    "sexual_abuse": [
        "rape", "molestation", "sexual assault", "grooming", "harassment",
    ],
    "domestic_abuse": [
        "abuse", "hitting", "unsafe at home", "threatening",
    ],
    "extortion_blackmail": [
        "blackmail", "blackmailing", "extort", "leak my photos",
        "leak my images", "share my photos", "threatening to post",
    ],
    "minor": [
        "i am a minor", "i'm a minor", "underage", "child abuse",
        "child exploitation", "my child is being", "my kid is being",
        "year old is being", "trafficking", "child trafficking",
    ],
    "urgent_crisis": [
        "emergency", "danger", "immediate danger",
    ],
}

CRISIS_RESPONSES = {
    "self_harm": (
        "I want to make sure you're okay. If you're in distress, please reach out to "
        "iCall (India): 9152987821, or Vandrevala Foundation: 1860-2662-345 "
        "(available 24/7). I'm here to help with your legal question too."
    ),
    "violence": (
        "Your safety is the priority. If you're in immediate danger, please call "
        "100 (Police) or 112 (Emergency). I'll do my best to help with your legal question."
    ),
    "sexual_abuse": (
        "I'm sorry you're dealing with this. You can contact the National Commission "
        "for Women helpline: 7827170170, or call 112 in an emergency. I'm here to help."
    ),
    "domestic_abuse": (
        "Please know you're not alone. The Women's Helpline (India) is available at "
        "181. If in immediate danger, call 112. I can also help with your legal question."
    ),
    "extortion_blackmail": (
        "I'm sorry you're dealing with this — you're not alone, and this is a "
        "recognized crime, not something you caused. Do not pay or comply with the "
        "demand. Save all evidence (screenshots, numbers, usernames) and report it to "
        "the Cyber Crime helpline: 1930, or online at cybercrime.gov.in. If you're in "
        "immediate danger, call 112. I can also help with the legal side."
    ),
    "minor": (
        "Child safety is critical. Please contact CHILDLINE India: 1098 (free, 24/7). "
        "For trafficking, call the Anti-Trafficking Helpline: 1800-419-8588."
    ),
    "urgent_crisis": (
        "If this is an emergency, please call 112 immediately. I'll also try to help "
        "with your question."
    ),
}


def detect_high_risk(query: str) -> Optional[str]:
    """Detect potentially high-risk queries and return the most relevant category.

    Returns the category whose matching phrase is the longest (most specific)
    match found, rather than the first category checked in dict order.
    """
    query_lower = query.lower()
    best_category = None
    best_phrase_len = 0

    for category, phrases in HIGH_RISK_KEYWORDS.items():
        for phrase in phrases:
            if phrase in query_lower and len(phrase) > best_phrase_len:
                best_category = category
                best_phrase_len = len(phrase)

    return best_category
STOPWORDS = {
    "i", "a", "an", "the", "is", "am", "are", "was", "were", "to", "in",
    "on", "for", "of", "and", "or", "my", "me", "it", "this", "that",
    "what", "do", "did", "does", "can", "you", "please",
}


def search_database(query: str) -> Optional[dict]:
    """Return the best-matching legal database entry, or None if no good match."""
    query_lower = query.lower()
    query_words = set(query_lower.split())

    best_entry = None
    best_score = 0

    for entry in LEGAL_DATABASE:
        searchable_texts = [
            entry.get("title", ""),
            entry.get("situation", ""),
            entry.get("category", ""),
        ] + entry.get("user_input_examples", [])

        score = 0
        for text in searchable_texts:
            text_lower = text.lower()
            if text_lower and text_lower in query_lower:
                score += 5
            text_words = set(text_lower.split()) - STOPWORDS
            score += len((query_words - STOPWORDS) & text_words)

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is None or best_score < 3:
        return None

    return best_entry


def format_db_context(entry: dict) -> str:
    """Format a database entry as reference text to enrich the Gemini prompt."""
    return (
        f"{entry['title']} ({entry['category']}): {entry['situation']} "
        f"Applicable laws: {entry['applicable_laws']}. "
        f"Rights: {entry['rights']}. "
        f"Suggested steps: {entry['action_steps']}. "
        f"Timeline: {entry['timeline']}."
    )


def build_prompt(query: str, db_entry: Optional[dict]) -> str:
    """Construct the final prompt, enriching with database context if available."""
    if db_entry:
        return f"Reference information: {format_db_context(db_entry)}\n\nUser question: {query}"
    return query

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"AURA backend starting. Legal database loaded: {len(LEGAL_DATABASE)} entries.")
    yield

app = FastAPI(
    title="AURA Legal Literacy Chatbot API",
    description="Backend for the AURA chatbot: Gemini-powered replies, "
                 "crisis detection, and a 75-entry legal reference database.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://aura-legal-guide.lovable.app"], 
    allow_credentials=True,
    allow_methods=["https://aura-legal-guide.lovable.app"],
    allow_headers=["https://aura-legal-guide.lovable.app"],
)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="The user's message to AURA")
    session_id: Optional[str] = Field(
        None, description="Existing session ID to continue a conversation. "
                           "Omit to start a new session."
    )
class CrisisInfo(BaseModel):
    category: str
    message: str
class ChatResponse(BaseModel):
    reply: str
    session_id: str
    crisis: Optional[CrisisInfo] = None
    matched_scenario_id: Optional[str] = None
class HealthResponse(BaseModel):
    status: str
    database_entries: int
@app.get("/health", response_model=HealthResponse)
async def health():
    """Simple health check for uptime monitoring."""
    return HealthResponse(status="ok", database_entries=len(LEGAL_DATABASE))

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Main chat endpoint.

    Send a message and (optionally) an existing session_id to continue a
    conversation. If session_id is omitted, a new session is created and
    returned — store it on the frontend and send it on subsequent requests
    so AURA remembers the conversation.

    The `crisis` field is populated alongside `reply` (never instead of it)
    when a high-risk phrase is detected, so the frontend can render it as a
    prominent banner above the normal reply.
    """
    user_message = req.message.strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message cannot be empty")

    session_id = req.session_id or str(uuid.uuid4())

    # 1. Crisis detection
    risk_category = detect_high_risk(user_message)
    crisis_payload = None
    if risk_category:
        crisis_payload = CrisisInfo(
            category=risk_category,
            message=CRISIS_RESPONSES.get(
                risk_category,
                "It seems like this might be a sensitive topic. Please consider "
                "reaching out to appropriate support services.",
            ),
        )

    # 2. Legal database lookup for grounding
    db_entry = search_database(user_message)
    matched_scenario_id = db_entry["id"] if db_entry else None

    # 3. Build prompt and call Gemini
    final_prompt = build_prompt(user_message, db_entry)
    chat_session = get_or_create_chat(session_id)

    try:
        response = chat_session.send_message(final_prompt)
        reply_text = response.text
    except Exception as e:  # pylint: disable=broad-exception-caught
        raise HTTPException(
            status_code=502,
            detail=f"Error communicating with AI: {e}",
        ) from e

    return ChatResponse(
        reply=reply_text,
        session_id=session_id,
        crisis=crisis_payload,
        matched_scenario_id=matched_scenario_id,
    )


@app.delete("/session/{session_id}")
async def end_session(session_id: str):
    """Let the frontend explicitly clear a session (e.g. on 'clear chat')."""
    existed = _sessions.pop(session_id, None) is not None # CRLF (\r\n)
    return {"deleted": existed} # CRLF (\r\n)
# End of file (EOF)
