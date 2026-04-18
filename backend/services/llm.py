"""
Response engine — works without any external LLM API.
Uses Qdrant semantic search + keyword intent detection + template formatting.
Voice calls go through Vapi (which handles LLM on its own credits).
"""
import re
import logging
import os
import requests
from typing import Dict, List, Any, Optional

from backend.config import (
    SUPPORTED_LANGUAGES,
    EMERGENCY_KEYWORDS,
    OPENROUTER_API_KEY,
    OPENAI_API_KEY,
    PRIMARY_LLM_MODEL,
    PRIMARY_LLM_TEMPERATURE,
)
from backend.prompts import get_shared_system_prompt
from backend.services.qdrant import search_legal_knowledge, get_user_memory

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

TOPIC_LABELS = {
    "theft": "theft",
    "theft_complaint": "theft",
    "fir_process": "FIR process",
    "property_rent": "property and rent issues",
    "family_personal": "family and personal issues",
    "workplace_issues": "employment and workplace issues",
    "domestic_violence": "domestic violence",
    "harassment": "harassment",
    "wage_theft": "unpaid wages",
    "land_dispute": "land dispute",
    "cyber_crime": "cyber crime",
    "consumer_rights": "consumer rights",
    "traffic_public": "traffic and public issues",
    "financial_banking": "financial and banking issues",
    "legal_aid": "free legal aid",
    "rti": "RTI",
    "child_rights": "child rights",
    "constitutional_rights": "constitutional rights",
    "criminal_law_basics": "criminal law basics",
    "general_legal_query": "legal issue",
}

INTENT_FALLBACK_QUERIES = {
    "theft_complaint": [
        "theft FIR stolen property zero FIR police station",
        "how to file FIR for theft in India",
    ],
    "fir_process": [
        "FIR process zero FIR nearest police station India",
        "where to file FIR police station zero FIR",
    ],
    "property_rent": [
        "rent agreement deposit eviction builder delay civil court rent tribunal consumer court India",
    ],
    "family_personal": [
        "family court divorce custody maintenance inheritance domestic violence India",
    ],
    "workplace_issues": [
        "salary not paid wrongful termination labour court POSH ICC workplace complaint India",
    ],
    "domestic_violence": [
        "domestic violence complaint women helpline protection officer India",
    ],
    "harassment": [
        "harassment complaint POSH police cyberstalking India",
    ],
    "wage_theft": [
        "unpaid wages labour commissioner complaint India",
    ],
    "land_dispute": [
        "land dispute encroachment complaint revenue court police India",
    ],
    "cyber_crime": [
        "cyber crime complaint 1930 cybercrime gov in India",
    ],
    "consumer_rights": [
        "consumer complaint refund eDaakhil district consumer forum India",
    ],
    "traffic_public": [
        "traffic challan accident claim MACT traffic police insurance claim India",
    ],
    "financial_banking": [
        "bank fraud unauthorized transaction RBI Ombudsman cheque bounce investment scam India",
    ],
    "legal_aid": [
        "free legal aid DLSA NALSA 15100 India",
    ],
    "rti": [
        "RTI application fee 30 days appeal India",
    ],
    "child_rights": [
        "child helpline 1098 POCSO child labour complaint India",
    ],
    "constitutional_rights": [
        "Constitution of India article 14 19 21 22 32 39A basic rights",
        "fundamental rights equality liberty arrest lawyer legal aid India",
    ],
    "criminal_law_basics": [
        "Bharatiya Nyaya Sanhita 2023 basic criminal law theft robbery extortion assault",
        "IPC and BNS difference theft robbery assault self defence India",
    ],
}

INTENT_PATTERNS: Dict[str, str] = {
    "theft_complaint": r"chori|theft|stolen|missing gold|missing jewelry|missing jewellery|gold missing|jewel(?:lery)?|jewellery|chain|ring|necklace|wallet|phone|फ़ोन|snatch|rob|loot|लूट",
    "domestic_violence": r"violen|hinsa|हिंसा|मार|domestic|abuse|beat|पीट|dv|498",
    "harassment": r"harass|posh|उत्पीड़|stalking|eve.?teas|molestation|छेड़",
    "wage_theft": r"wage|vetan|वेतन|salary|pay|भुगतान|mazduri|मज़दूरी|labour|labor",
    "land_dispute": r"land|bhumi|भूमि|ज़मीन|zameen|property|सम्पत्ति|plot|encroach",
    "cyber_crime": r"cyber|साइबर|hack|hacking|online|ऑनलाइन|fraud|धोखा|धोखाधड़ी|फ्रॉड|scam|phishing|sextort|otp fraud|upi fraud|identity theft|अपराध",
    "consumer_rights": r"consumer|उपभोक्ता|refund|product|defect|warranty|खराब",
    "rti": r"rti|सूचना|right to info|आरटीआई|information act",
    "fir_process": r"fir|एफ़आईआर|first information|zero fir|police station|थाना",
    "legal_aid": r"free legal|legal aid|nalsa|नालसा|dlsa|free lawyer|15100",
    "child_rights": r"child|बच्च|pocso|juvenile|1098|minor",
    "emergency": r"emergency|help me|bachao|बचाओ|danger|khatra|खतरा|jaan|kill|मार",
}

INTENT_PATTERNS.update({
    "property_rent": r"landlord|tenant|rent|deposit|evict|eviction|lease|builder|possession|property sale|encroach|encroachment|boundary|parking|society dispute|maintenance dispute|unauthorized construction",
    "family_personal": r"divorce|custody|alimony|maintenance|inheritance|will dispute|elder abuse|forced marriage|second marriage|live.?in|adoption|child neglect|marital dispute|dowry",
    "workplace_issues": r"salary not paid|wrongful termination|terminated|overtime|pf|esi|workplace discrimination|blacklist|experience letter|bond|contract dispute|job fraud|fake job|resignation issue|internship exploitation",
    "traffic_public": r"traffic challan|drunk driving|accident|hit and run|road rage|vehicle theft|driving license|insurance claim|pollution certificate|public nuisance|mact",
    "financial_banking": r"loan harassment|credit score|cibil|bank fraud|unauthorized transaction|atm issue|insurance claim rejection|nbfc|cheque bounce|debt recovery|investment scam|upi scam|credit card fraud",
    "constitutional_rights": r"constitution|fundamental right|article 14|article 19|article 21|article 22|article 32|article 39a|equality before law|personal liberty|arrest rights|constitutional right",
    "criminal_law_basics": r"\bipc\b|\bbns\b|bharatiya nyaya sanhita|criminal law|robbery|extortion|wrongful restraint|wrongful confinement|self defence|private defence|assault|criminal force",
})

EMERGENCY_RESPONSE: Dict[str, str] = {
    "en": (
        "**EMERGENCY — Call for help immediately:**\n\n"
        "- Police: **100**\n"
        "- Women Helpline: **181** (24/7)\n"
        "- Emergency (all services): **112**\n"
        "- Child Helpline: **1098**\n"
        "- Cyber Crime: **1930**\n\n"
        "You are not alone. Help is available right now. If you are in physical danger, call 112 immediately."
    ),
    "hi": (
        "**आपातकाल — तुरन्त सहायता के लिए कॉल करें:**\n\n"
        "- पुलिस: **100**\n"
        "- महिला हेल्पलाइन: **181** (24/7)\n"
        "- आपातकाल (सभी सेवाएँ): **112**\n"
        "- बाल हेल्पलाइन: **1098**\n"
        "- साइबर अपराध: **1930**\n\n"
        "आप अकेले नहीं हैं। सहायता अभी उपलब्ध है। यदि आप शारीरिक खतरे में हैं, तो तुरन्त 112 पर कॉल करें।"
    ),
}


def detect_intent(user_message: str) -> Dict[str, Any]:
    """
    Detect the intent and language of the user's message.
    """
    if not user_message or not isinstance(user_message, str):
        return {
            "intent": "general_legal_query",
            "language": "en",
            "urgency": False,
            "summary": "",
        }

    lower = user_message.lower()
    urgency = any(kw in lower for kw in EMERGENCY_KEYWORDS)

    if _looks_like_theft_or_fir_query(lower):
        detected_lang = "hi" if any("\u0900" <= c <= "\u097F" for c in user_message) else "en"
        return {
            "intent": "fir_process",
            "language": detected_lang,
            "urgency": urgency,
            "summary": user_message[:100],
        }

    if _looks_like_rent_deposit_query(lower):
        detected_lang = "hi" if any("\u0900" <= c <= "\u097F" for c in user_message) else "en"
        return {
            "intent": "property_rent",
            "language": detected_lang,
            "urgency": urgency,
            "summary": user_message[:100],
        }

    detected_intent = "general_legal_query"
    for intent, pattern in INTENT_PATTERNS.items():
        if re.search(pattern, lower, re.IGNORECASE):
            detected_intent = intent
            break

    is_hindi = any("\u0900" <= c <= "\u097F" for c in user_message)
    detected_lang = "hi" if is_hindi else "en"

    return {
        "intent": detected_intent,
        "language": detected_lang,
        "urgency": urgency,
        "summary": user_message[:100],
    }


def generate_response(
    user_id: str,
    user_message: str,
    conversation: List[Dict[str, Any]],
    language_code: str = "en",
) -> Dict[str, Any]:
    """
    Generate a response using Qdrant RAG search (no LLM API needed).
    For voice calls, Vapi handles the LLM on its own credits.
    """
    try:
        intent_data = detect_intent(user_message)
        intent = intent_data.get("intent", "general_legal_query")
        detected_lang = _resolve_response_language(language_code, intent_data.get("language", "en"))
        urgency = intent_data.get("urgency", False)

        if urgency or intent == "emergency":
            emergency_text = EMERGENCY_RESPONSE.get(detected_lang, EMERGENCY_RESPONSE["en"])
            legal_results = search_legal_knowledge(user_message, top_k=2)
            if legal_results:
                emergency_text += "\n\n---\n\n" + _format_legal_results(legal_results, detected_lang)
            return {
                "response": emergency_text,
                "intent": "emergency",
                "language": detected_lang,
                "follow_up": False,
                "urgency": True,
                "source": "backend_fallback",
                "source_detail": "emergency_path",
            }

        legal_results = _search_legal_knowledge_with_fallback(user_message, intent, top_k=6)
        memories = get_user_memory(user_id, top_k=2)

        intent_results = _filter_results_for_intent(legal_results, intent)
        strong_results = [r for r in legal_results if r["score"] >= 0.25]
        strong_intent_results = [r for r in intent_results if r["score"] >= 0.25]
        response_results = strong_intent_results or intent_results or strong_results

        if intent == "property_rent" and _looks_like_rent_deposit_query(user_message.lower()):
            deposit_specific_results = [
                r for r in legal_results
                if r.get("category") == "property_rent" and r.get("score", 0) > 0.2
            ]
            if deposit_specific_results:
                response_results = deposit_specific_results[:3]

        source = "backend_fallback"
        source_detail = None

        if _primary_llm_available():
            # Use the configured primary LLM so Vapi and backend text chat stay aligned.
            context_source = response_results or [r for r in legal_results if r["score"] > 0.2]
            context_str = "\n".join(
                [f"[{r['category'].title()}] {r['content']}" for r in context_source if r["score"] > 0.2]
            )
            reply, openai_error = _generate_with_primary_llm(user_message, context_str, detected_lang, conversation)
            if reply:
                source = "openrouter" if OPENROUTER_API_KEY else "openai"
                source_detail = "primary_llm"
            else:
                source_detail = openai_error
                # Fallback if Gemini fails
                if response_results:
                    reply = _build_grounded_response(user_message, response_results, intent, detected_lang)
                else:
                    reply = _intent_or_generic_response(user_message, intent, detected_lang)
        else:
            if response_results:
                reply = _build_grounded_response(user_message, response_results, intent, detected_lang)
            else:
                reply = _intent_or_generic_response(user_message, intent, detected_lang)

        reply = _normalize_reply(reply, detected_lang)

        store_turn(user_id, user_message, reply, intent)

        return {
            "response": reply,
            "intent": intent,
            "language": detected_lang,
            "follow_up": True,
            "urgency": False,
            "source": source,
            "source_detail": source_detail,
        }
    except Exception as e:
        logger.error(f"Error generating response for user {user_id}: {str(e)}", exc_info=True)
        return {
            "response": "I apologize, but I'm having trouble processing your request right now. Please try again or contact emergency services if this is urgent.",
            "intent": "error",
            "language": language_code,
            "follow_up": False,
            "urgency": False,
            "source": "backend_fallback",
            "source_detail": "internal_error",
        }


def _primary_llm_available() -> bool:
    return bool(OPENROUTER_API_KEY or OPENAI_API_KEY)


def _generate_with_primary_llm(user_message: str, context: str, lang: str, conversation: list) -> tuple[str, str | None]:
    if OPENROUTER_API_KEY:
        return _generate_with_openrouter(user_message, context, lang, conversation)
    if OPENAI_API_KEY:
        return _generate_with_openai(user_message, context, lang, conversation)
    return "", "llm_not_configured"


def _generate_with_openrouter(user_message: str, context: str, lang: str, conversation: list) -> tuple[str, str | None]:
    """Make REST API call to OpenRouter using the OpenAI-compatible endpoint."""
    url = "https://openrouter.ai/api/v1/chat/completions"
    payload = {
        "model": PRIMARY_LLM_MODEL,
        "messages": _build_llm_messages(user_message, context, lang, conversation),
        "temperature": PRIMARY_LLM_TEMPERATURE,
    }
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if not resp.ok:
            source_detail = None
            try:
                error_data = resp.json()
                source_detail = (
                    error_data.get("error", {}).get("code")
                    or error_data.get("error", {}).get("type")
                    or error_data.get("error", {}).get("message")
                )
            except Exception:
                source_detail = None
            logger.error(
                "OpenRouter generation failed: status=%s model=%s body=%s",
                resp.status_code,
                PRIMARY_LLM_MODEL,
                resp.text[:1000],
            )
            resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        logger.error("OpenRouter generation failed: model=%s error=%s", PRIMARY_LLM_MODEL, e)
        if "source_detail" in locals() and source_detail:
            return "", f"openrouter_{source_detail}"
        return "", "openrouter_request_failed"


def _build_llm_messages(user_message: str, context: str, lang: str, conversation: list) -> list:
    messages = [{"role": "system", "content": get_shared_system_prompt(lang)}]

    for msg in conversation[-4:]:
        role = msg.get("role")
        if role in ("user", "assistant") and msg.get("text"):
            messages.append({"role": role, "content": msg["text"]})

    context_block = context.strip() if context.strip() else "No additional legal context retrieved."
    messages.append({
        "role": "user",
        "content": (
            f"Legal Context:\n{context_block}\n\n"
            f"Current User Message:\n{user_message}\n\n"
            "Answer using the legal context when it is relevant. "
            "If the context is not enough, say so clearly instead of making up precise legal details."
        ),
    })
    return messages


def _generate_with_openai(user_message: str, context: str, lang: str, conversation: list) -> tuple[str, str | None]:
    """Make REST API call to OpenAI using the shared prompt and primary model."""
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": PRIMARY_LLM_MODEL,
        "messages": _build_llm_messages(user_message, context, lang, conversation),
        "temperature": PRIMARY_LLM_TEMPERATURE,
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if not resp.ok:
            source_detail = None
            try:
                error_data = resp.json()
                source_detail = error_data.get("error", {}).get("type")
            except Exception:
                source_detail = None
            logger.error(
                "OpenAI generation failed: status=%s model=%s body=%s",
                resp.status_code,
                PRIMARY_LLM_MODEL,
                resp.text[:1000],
            )
            resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip(), None
    except Exception as e:
        logger.error("OpenAI generation failed: model=%s error=%s", PRIMARY_LLM_MODEL, e)
        if "source_detail" in locals() and source_detail:
            return "", source_detail
        return "", "openai_request_failed"


def _generate_with_gemini(user_message: str, context: str, lang: str, conversation: list) -> str:
    """Fallback Gemini path using the same shared system prompt."""
    messages = _build_llm_messages(user_message, context, lang, conversation)
    prompt_parts = [f"System: {messages[0]['content']}"]
    for msg in messages[1:]:
        role = "User" if msg["role"] == "user" else "NyayaVoice"
        prompt_parts.append(f"{role}: {msg['content']}")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": "\n\n".join(prompt_parts)}]}],
        "generationConfig": {"temperature": PRIMARY_LLM_TEMPERATURE}
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        return ""


def get_retrieval_candidates(user_message: str, intent: str = "") -> list:
    candidates = [user_message.strip()]
    lower = user_message.lower()
    if intent == "property_rent" and _looks_like_rent_deposit_query(lower):
        targeted_queries = [
            "landlord not returning security deposit rent agreement legal notice India",
            "tenant deposit refund complaint rent tribunal civil court India",
        ]
        for query in targeted_queries:
            if query not in candidates:
                candidates.append(query)
    if intent:
        for query in INTENT_FALLBACK_QUERIES.get(intent, []):
            if query not in candidates:
                candidates.append(query)
    return [candidate for candidate in candidates if candidate]


def _search_legal_knowledge_with_fallback(user_message: str, intent: str, top_k: int = 6) -> list:
    merged_results = []
    seen = {}

    for query in get_retrieval_candidates(user_message, intent):
        for result in search_legal_knowledge(query, top_k=top_k):
            key = (result.get("category", ""), result.get("content", ""))
            existing = seen.get(key)
            if not existing or result.get("score", 0) > existing.get("score", 0):
                seen[key] = result

    merged_results = list(seen.values())
    merged_results.sort(key=lambda item: item.get("score", 0), reverse=True)
    return merged_results[:top_k]


def store_turn(user_id, user_message, reply, intent):
    """Store the conversation turn for memory."""
    from backend.services.qdrant import store_conversation
    try:
        store_conversation(
            user_id=user_id,
            conversation=[
                {"role": "user", "text": user_message},
                {"role": "assistant", "text": reply[:300]},
            ],
            case_type=intent,
        )
    except Exception as e:
        logger.warning(f"Failed to store turn: {e}")


def _format_legal_results(results: list, lang: str) -> str:
    lines = []
    for r in results:
        content = _localize_legal_text(r["content"], lang)
        category = _localize_topic_label(r["category"], lang)
        score = r["score"]
        if score < 0.25:
            continue
        lines.append(f"**[{category}]** {content}")

    if not lines:
        return _generic_guidance(lang)

    if lang == "hi":
        header = "**आपके प्रश्न से सम्बन्धित कानूनी जानकारी:**"
        footer = "\n\nक्या आप इनमें से किसी विषय पर और विस्तार से जानना चाहते हैं?"
    else:
        header = "**Legal information relevant to your query:**"
        footer = "\n\nWould you like to know more about any of these topics?"

    return header + "\n\n" + "\n\n".join(lines) + footer


def _build_grounded_response(user_message: str, results: list, intent: str, lang: str) -> str:
    top_results = results[:3]
    primary_topic = _localize_topic_label(
        intent if intent != "general_legal_query" else top_results[0]["category"],
        lang,
    )

    if lang == "hi":
        intro = f"आपके सवाल के हिसाब से, {primary_topic} के लिए यह सबसे काम की जानकारी है:"
        next_steps_label = "अगले कदम:"
        follow_up = "अगर आप चाहें, तो मैं इसी विषय पर एक छोटा ड्राफ्ट या अगले कदम भी बता सकता हूँ।"
    else:
        intro = f"Based on your question, here is the most relevant information about {primary_topic}:"
        next_steps_label = "Next steps:"
        follow_up = "If you want, I can also turn this into a short step-by-step plan or draft."

    key_points = _extract_key_points(top_results, lang)
    response_lines = [intro, ""]
    response_lines.extend(f"- {point}" for point in key_points[:4])

    next_steps = _suggest_next_steps(intent, top_results, lang)
    if next_steps:
        response_lines.extend(["", next_steps_label])
        response_lines.extend(f"- {step}" for step in next_steps[:3])

    specific_question = _detect_specific_question(user_message, lang)
    if specific_question and lang != "hi":
        response_lines.extend(["", f"In short: {specific_question}"])
    elif specific_question and lang == "hi":
        response_lines.extend(["", f"संक्षेप में: {specific_question}"])

    response_lines.extend(["", follow_up])
    return "\n".join(response_lines)


def _filter_results_for_intent(results: list, intent: str) -> list:
    if not results:
        return []
    intent_categories = {
        "theft_complaint": {"theft", "fir_process"},
        "fir_process": {"fir_process", "theft"},
        "property_rent": {"property_rent", "land_dispute", "consumer_rights"},
        "family_personal": {"family_personal", "domestic_violence"},
        "workplace_issues": {"workplace_issues", "wage_theft", "harassment"},
        "domestic_violence": {"domestic_violence"},
        "harassment": {"harassment", "cyber_crime"},
        "wage_theft": {"wage_theft"},
        "land_dispute": {"land_dispute"},
        "cyber_crime": {"cyber_crime"},
        "consumer_rights": {"consumer_rights"},
        "traffic_public": {"traffic_public", "theft", "fir_process"},
        "financial_banking": {"financial_banking", "cyber_crime", "consumer_rights"},
        "legal_aid": {"legal_aid"},
        "rti": {"rti"},
        "child_rights": {"child_rights"},
        "constitutional_rights": {"constitutional_rights", "legal_aid"},
        "criminal_law_basics": {"criminal_law_basics", "fir_process", "theft"},
    }
    allowed = intent_categories.get(intent, set())
    filtered = [r for r in results if r.get("category") in allowed]
    return filtered[:3]


def _extract_key_points(results: list, lang: str = "en") -> list:
    seen = set()
    points = []
    for result in results:
        sentences = re.split(r"(?<=[.!?])\s+", result["content"].strip())
        for sentence in sentences:
            cleaned = _localize_legal_text(sentence.strip().replace("\n", " "), lang)
            if len(cleaned) < 25:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            points.append(cleaned)
    return points


def _suggest_next_steps(intent: str, results: list, lang: str) -> list:
    category = intent if intent != "general_legal_query" else results[0]["category"]
    steps_en = {
        "theft_complaint": [
            "Note what was stolen, when it happened, and where it happened.",
            "Go to the nearest police station and ask to file an FIR or Zero FIR.",
            "Keep a free copy of the FIR and any proof like bills, IMEI number, or photos.",
        ],
        "theft": [
            "Note what was stolen, when it happened, and where it happened.",
            "Go to the nearest police station and ask to file an FIR or Zero FIR.",
            "Keep a free copy of the FIR and any proof like bills, IMEI number, or photos.",
        ],
        "fir_process": [
            "Prepare the basic facts: what happened, when, where, and who was involved.",
            "Ask for a free FIR copy after registration.",
            "If the police refuse, complain to the Superintendent of Police or seek court directions.",
        ],
        "property_rent": [
            "Collect the agreement, payment proof, bills, chats, and property papers.",
            "Send a legal notice before filing if the dispute is about deposit, eviction, or possession.",
            "File before the Civil Court, Rent Tribunal, or Consumer Court depending on the issue.",
        ],
        "family_personal": [
            "Keep marriage, residence, income, and abuse-related records ready.",
            "If there is violence or threats, approach the police or Protection Officer immediately.",
            "For divorce, custody, maintenance, or inheritance issues, file the right petition in Family Court or Civil Court.",
        ],
        "workplace_issues": [
            "Collect your offer letter, salary proof, emails, and internal complaint records.",
            "Raise the issue internally first if appropriate, especially in workplace policy cases.",
            "For salary, termination, or labour issues, send notice and approach the Labour Court or labour authority.",
        ],
        "domestic_violence": [
            "If there is immediate danger, call 181 or 112 right away.",
            "Save messages, photos, medical papers, or witness details.",
            "You can approach the police, a Protection Officer, or an NGO for help.",
        ],
        "cyber_crime": [
            "Save screenshots, transaction IDs, phone numbers, and links.",
            "Report quickly at cybercrime.gov.in or call 1930.",
            "If money was lost, also file an FIR or police complaint.",
        ],
        "consumer_rights": [
            "Keep the bill, warranty, screenshots, and seller communication.",
            "Ask the seller for refund or replacement in writing.",
            "If unresolved, file a complaint on eDaakhil or before the District Consumer Forum.",
        ],
        "traffic_public": [
            "Keep the FIR, challan, photos, insurance papers, and medical records if relevant.",
            "Report accidents, vehicle theft, or public-safety issues to the police without delay.",
            "For accident compensation, insurance disputes, or challan matters, approach MACT, the insurer, or the traffic authority.",
        ],
        "financial_banking": [
            "Inform the bank or platform immediately and preserve statements, receipts, and messages.",
            "If it is fraud, report to police or cybercrime authorities quickly.",
            "Use the RBI Ombudsman, civil court, or cheque-bounce process depending on the dispute.",
        ],
        "legal_aid": [
            "Contact the District Legal Services Authority in your district.",
            "Call NALSA helpline 15100 for free legal help.",
            "Keep your ID and basic case papers ready when you call or visit.",
        ],
    }
    steps_hi = {
        "theft_complaint": [
            "क्या चोरी हुआ, कब हुआ और कहाँ हुआ, यह लिख लें।",
            "नजदीकी पुलिस स्टेशन में जाकर FIR या Zero FIR दर्ज कराने को कहें।",
            "FIR की मुफ्त कॉपी और बिल, IMEI नंबर या फोटो जैसे सबूत संभालकर रखें।",
        ],
        "theft": [
            "क्या चोरी हुआ, कब हुआ और कहाँ हुआ, यह लिख लें।",
            "नजदीकी पुलिस स्टेशन में जाकर FIR या Zero FIR दर्ज कराने को कहें।",
            "FIR की मुफ्त कॉपी और बिल, IMEI नंबर या फोटो जैसे सबूत संभालकर रखें।",
        ],
        "fir_process": [
            "घटना के मुख्य तथ्य तैयार रखें: क्या हुआ, कब, कहाँ और कौन शामिल था।",
            "FIR दर्ज होने के बाद उसकी मुफ्त कॉपी जरूर लें।",
            "अगर पुलिस मना करे, तो एसपी को शिकायत करें या अदालत से आदेश मांगें।",
        ],
        "domestic_violence": [
            "अगर तुरंत खतरा है, तो 181 या 112 पर अभी कॉल करें।",
            "मैसेज, फोटो, मेडिकल पेपर या गवाह की जानकारी सुरक्षित रखें।",
            "आप पुलिस, Protection Officer या NGO से मदद ले सकती हैं।",
        ],
        "cyber_crime": [
            "स्क्रीनशॉट, ट्रांजैक्शन आईडी, फोन नंबर और लिंक सुरक्षित रखें।",
            "जल्दी cybercrime.gov.in पर रिपोर्ट करें या 1930 पर कॉल करें।",
            "अगर पैसे गए हैं, तो FIR या पुलिस शिकायत भी करें।",
        ],
        "consumer_rights": [
            "बिल, वारंटी, स्क्रीनशॉट और विक्रेता से हुई बात सुरक्षित रखें।",
            "रिफंड या रिप्लेसमेंट के लिए लिखित में मांग करें।",
            "समाधान न मिले तो eDaakhil या जिला उपभोक्ता फोरम में शिकायत करें।",
        ],
        "legal_aid": [
            "अपने जिले के DLSA से संपर्क करें।",
            "मुफ्त कानूनी सहायता के लिए NALSA हेल्पलाइन 15100 पर कॉल करें।",
            "फोन या विजिट से पहले अपनी पहचान और केस के कागज तैयार रखें।",
        ],
    }
    mapping = steps_hi if lang == "hi" else steps_en
    return mapping.get(category, [])


def _detect_specific_question(user_message: str, lang: str = "en") -> str:
    lower = user_message.lower()
    if (
        ("where" in lower and "fir" in lower)
        or ("report" in lower and "fir" in lower)
        or _looks_like_theft_or_fir_query(lower)
    ):
        return (
            "आप FIR नजदीकी किसी भी पुलिस स्टेशन में दर्ज करा सकते हैं। अगर घटना किसी दूसरे इलाके की है, तो भी Zero FIR दर्ज हो सकती है।"
            if lang == "hi"
            else "You can go to the nearest police station to report an FIR, and if the incident happened elsewhere you can still ask for a Zero FIR."
        )
    if "how to file" in lower or ("file" in lower and "case" in lower):
        return (
            "आप पहले घटना के तथ्य साफ़ लिखें, फिर सही प्राधिकरण के पास शिकायत या FIR दर्ज करें और उसकी कॉपी रखें।"
            if lang == "hi"
            else "You usually start by writing the facts clearly, then file the complaint or FIR with the correct authority and keep a copy."
        )
    if "fir" in lower and ("how" in lower or "file" in lower):
        return (
            "आप नजदीकी पुलिस स्टेशन में FIR दर्ज करा सकते हैं, और कई मामलों में Zero FIR भी दर्ज हो सकती है।"
            if lang == "hi"
            else "You can file an FIR at the nearest police station, and in many cases even as a Zero FIR."
        )
    if "legal aid" in lower or "free lawyer" in lower:
        return (
            "मुफ्त कानूनी सहायता DLSA और NALSA हेल्पलाइन 15100 के माध्यम से मिल सकती है।"
            if lang == "hi"
            else "Free legal aid is available through DLSA and NALSA helpline 15100."
        )
    return ""


def _clarifying_or_generic_response(user_message: str, intent: str, lang: str) -> str:
    if _is_vague_question(user_message):
        if lang == "hi":
            topic = TOPIC_LABELS.get(intent, "कानूनी समस्या")
            return (
                f"मैं मदद कर सकता हूँ, लेकिन आपका सवाल अभी थोड़ा सामान्य है। "
                f"कृपया एक लाइन में बताइए कि {topic} में आपको क्या जानना है: "
                f"क्या करना है, कहाँ शिकायत करनी है, कौन से कागज़ चाहिए, या आगे के कदम क्या हैं?"
            )
        topic = TOPIC_LABELS.get(intent, "legal issue")
        return (
            f"I can help, but your question is still a bit broad. "
            f"Please tell me in one line what you want to know about {topic}: "
            f"what to do, where to file, what documents are needed, or what the next step is."
        )
    return _generic_guidance(lang)


def _detect_guidance_scope(user_message: str, lang: str = "en") -> str:
    lower = user_message.lower()
    where_terms = ["where", "where to file", "where to complain", "where should", "kahaan", "कहाँ", "कहां"]
    docs_terms = ["document", "documents", "proof", "evidence", "papers", "docs", "दस्तावेज", "सबूत", "प्रूफ", "कागज"]
    what_terms = ["what", "what to do", "steps", "next step", "next steps", "how", "क्या", "क्या करें", "अगला कदम", "कैसे"]

    if any(term in lower for term in docs_terms):
        return "documents"
    if any(term in lower for term in where_terms):
        return "where"
    if any(term in lower for term in what_terms):
        return "what"
    return "general"


def _compose_topic_guidance(
    user_message: str,
    lang: str,
    title_en: str,
    title_hi: str,
    what_en: str,
    where_en: str,
    docs_en: str,
    what_hi: str,
    where_hi: str,
    docs_hi: str,
) -> str:
    scope = _detect_guidance_scope(user_message, lang)
    title = title_hi if lang == "hi" else title_en

    if lang == "hi":
        sections = {
            "what": f"**{title}**\n\n**क्या करें:** {what_hi}",
            "where": f"**{title}**\n\n**कहाँ शिकायत करें:** {where_hi}",
            "documents": f"**{title}**\n\n**आवश्यक दस्तावेज:** {docs_hi}",
            "general": (
                f"**{title}**\n\n"
                f"**क्या करें:** {what_hi}\n\n"
                f"**कहाँ शिकायत करें:** {where_hi}\n\n"
                f"**आवश्यक दस्तावेज:** {docs_hi}"
            ),
        }
    else:
        sections = {
            "what": f"**{title}**\n\n**What to do:** {what_en}",
            "where": f"**{title}**\n\n**Where to file:** {where_en}",
            "documents": f"**{title}**\n\n**Documents needed:** {docs_en}",
            "general": (
                f"**{title}**\n\n"
                f"**What to do:** {what_en}\n\n"
                f"**Where to file:** {where_en}\n\n"
                f"**Documents needed:** {docs_en}"
            ),
        }

    return sections.get(scope, sections["general"])


def _intent_or_generic_response(user_message: str, intent: str, lang: str) -> str:
    intent_reply = _intent_guidance(intent, user_message, lang)
    if intent_reply:
        return intent_reply
    return _clarifying_or_generic_response(user_message, intent, lang)


def _intent_guidance(intent: str, user_message: str, lang: str) -> str:
    if intent == "fir_process":
        return _fir_guidance(user_message, lang)
    if intent == "theft_complaint":
        return _theft_guidance(lang)
    if intent == "property_rent":
        deposit_reply = _deposit_refund_guidance(user_message, lang)
        if deposit_reply:
            return deposit_reply
        return _property_rent_guidance(user_message, lang)
    if intent == "family_personal":
        return _family_personal_guidance(user_message, lang)
    if intent == "workplace_issues":
        return _workplace_issues_guidance(user_message, lang)
    if intent == "domestic_violence":
        return _domestic_violence_guidance(user_message, lang)
    if intent == "cyber_crime":
        return _cyber_guidance(user_message, lang)
    if intent == "consumer_rights":
        return _consumer_guidance(user_message, lang)
    if intent == "traffic_public":
        return _traffic_public_guidance(user_message, lang)
    if intent == "financial_banking":
        return _financial_banking_guidance(user_message, lang)
    if intent == "legal_aid":
        return _legal_aid_guidance(lang)
    if intent == "constitutional_rights":
        return _constitutional_rights_guidance(lang)
    if intent == "criminal_law_basics":
        return _criminal_law_basics_guidance(lang)
    return ""


def _fir_guidance(user_message: str, lang: str) -> str:
    short_answer = _detect_specific_question(user_message, lang)
    if lang == "hi":
        lines = [
            "FIR के लिए आप नजदीकी पुलिस स्टेशन जा सकते हैं.",
            "अगर घटना किसी दूसरे इलाके की है, तब भी आप Zero FIR दर्ज कराने को कह सकते हैं.",
            "अपने साथ यह जानकारी रखें: क्या हुआ, कब हुआ, कहाँ हुआ, और अगर पता हो तो आरोपी या गवाह की जानकारी.",
            "FIR दर्ज होने के बाद उसकी मुफ्त कॉपी जरूर लें.",
        ]
        close = "अगर आप चाहें, तो मैं FIR के लिए एक ready-to-file draft भी बना सकता हूँ।"
    else:
        lines = [
            "You can go to the nearest police station to file an FIR.",
            "If the incident happened in another area, you can still ask for a Zero FIR and the police should transfer it to the correct station.",
            "Carry the basic facts: what happened, when it happened, where it happened, and any suspect or witness details if available.",
            "Ask for a free copy of the FIR after it is registered.",
        ]
        close = "If you want, I can also help draft the FIR in a ready-to-file format."

    response = "\n".join(f"- {line}" for line in lines)
    if short_answer:
        prefix = "संक्षेप में: " if lang == "hi" else "In short: "
        response = prefix + short_answer + "\n\n" + response
    return response + "\n\n" + close


def _theft_guidance(lang: str) -> str:
    if lang == "hi":
        return (
            "- चोरी की घटना के लिए नजदीकी पुलिस स्टेशन में FIR या Zero FIR दर्ज कराएँ.\n"
            "- क्या चोरी हुआ, कब हुआ, कहाँ हुआ और कोई सबूत हो तो साथ रखें.\n"
            "- FIR की मुफ्त कॉपी लें.\n\n"
            "अगर आप चाहें, तो मैं चोरी की शिकायत का ड्राफ्ट तैयार कर सकता हूँ।"
        )
    return (
        "- For theft, go to the nearest police station and ask to file an FIR or Zero FIR.\n"
        "- Keep the basic facts ready: what was stolen, when, where, and any proof you have.\n"
        "- Take a free copy of the FIR after registration.\n\n"
        "If you want, I can help draft the theft complaint for you."
    )


def _deposit_refund_guidance(user_message: str, lang: str) -> str:
    lower = user_message.lower()
    keywords = [
        "deposit",
        "security deposit",
        "advance",
        "refund",
        "not returning",
        "return my money",
        "deduct",
        "deduction",
    ]
    if not any(keyword in lower for keyword in keywords):
        return ""

    if lang == "hi":
        return (
            "- अगर मकान मालिक आपका deposit वापस नहीं कर रहा है, तो पहले rent agreement में refund, notice period, damage deduction, और move-out terms देखें.\n"
            "- Agreement, deposit payment proof, rent receipts, bank statement, chats/messages, move-out photos/videos, और handover proof सुरक्षित रखें.\n"
            "- पहले written notice या legal notice भेजकर deposit refund साफ़ शब्दों में माँगें और payment के लिए reasonable time दें.\n"
            "- अगर फिर भी refund नहीं मिलता, तो area के हिसाब से Rent Authority/Rent Tribunal या Civil Court में शिकायत या recovery case पर विचार किया जा सकता है.\n\n"
            "अगर आप चाहें, तो मैं landlord को भेजने के लिए deposit-refund notice draft कर सकता हूँ."
        )
    return (
        "- If your landlord is not returning your deposit, first check the rent agreement for refund, notice-period, damage-deduction, and move-out terms.\n"
        "- Keep the agreement, deposit payment proof, rent receipts, bank statement, chats/messages, move-out photos/videos, and handover proof safely.\n"
        "- Send a written notice or legal notice clearly asking for the deposit refund and give a reasonable deadline for payment.\n"
        "- If the deposit is still not returned, you may need to approach the Rent Authority/Rent Tribunal or the Civil Court, depending on your area and the tenancy setup.\n\n"
        "If you want, I can also draft a deposit-refund notice to the landlord."
    )


def _property_rent_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Property & Rent Issues",
        title_hi="संपत्ति और किराया विवाद",
        what_en="Collect the agreement and payment proof first, then send a legal notice.",
        where_en="Civil Court or Rent Tribunal. For builder matters, Consumer Court may also apply.",
        docs_en="Rent agreement, payment receipts, bank statement, chats/emails, and photos/videos.",
        what_hi="एग्रीमेंट और पेमेंट का सबूत इकट्ठा करें, फिर लीगल नोटिस भेजें।",
        where_hi="सिविल कोर्ट या रेंट ट्रिब्यूनल। बिल्डर मामलों में कंज्यूमर कोर्ट भी जा सकते हैं।",
        docs_hi="किराया एग्रीमेंट, पेमेंट रसीद, बैंक स्टेटमेंट, चैट/ईमेल, और फोटो/वीडियो।",
    )
    if lang == "hi":
        return (
            "- एग्रीमेंट, भुगतान रसीद, बैंक रिकॉर्ड, चैट, फोटो और प्रॉपर्टी पेपर सुरक्षित रखें.\n"
            "- डिपॉजिट, बेदखली, कब्जा या बिल्डर देरी जैसे मामलों में पहले legal notice भेजना उपयोगी होता है.\n"
            "- मामला Civil Court, Rent Tribunal, या builder मामलों में Consumer Court में जा सकता है.\n\n"
            "अगर आप चाहें, तो मैं property/rent dispute के लिए अगले कदम और जरूरी documents अलग से सूचीबद्ध कर सकता हूँ."
        )
    return (
        "- Keep the rent agreement, payment receipts, bank statement, chats/emails, and photos/videos safely.\n"
        "- In deposit, illegal-eviction, rent-agreement, or builder-delay disputes, a legal notice is often the first practical step.\n"
        "- Depending on the issue, you may need to file before the Civil Court, Rent Tribunal, or Consumer Court.\n\n"
        "If you want, I can list the exact documents and next steps for your property or rent issue."
    )


def _family_personal_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Family Issues",
        title_hi="पारिवारिक मामले",
        what_en="Approach the police or relevant authority and preserve evidence.",
        where_en="Family Court or Police Station, depending on the issue.",
        docs_en="Marriage certificate, medical reports, chats/recordings, and income proof.",
        what_hi="पुलिस या संबंधित अधिकारी से संपर्क करें और सबूत सुरक्षित रखें।",
        where_hi="मामले के अनुसार फैमिली कोर्ट या पुलिस स्टेशन।",
        docs_hi="विवाह प्रमाण पत्र, मेडिकल रिपोर्ट, चैट/रिकॉर्डिंग, और आय का प्रमाण।",
    )
    if lang == "hi":
        return (
            "- शादी, आय, निवास, बच्चे, मेडिकल रिकॉर्ड, चैट और अन्य पारिवारिक दस्तावेज सुरक्षित रखें.\n"
            "- अगर हिंसा, धमकी, या दहेज उत्पीड़न है, तो पुलिस या Protection Officer से तुरंत संपर्क करें.\n"
            "- Divorce, custody, maintenance, inheritance, or will disputes आमतौर पर Family Court या Civil Court में जाते हैं.\n\n"
            "अगर आप चाहें, तो मैं आपके family matter के हिसाब से where to file और documents needed बता सकता हूँ."
        )
    return (
        "- Keep the marriage certificate, medical reports, chats/recordings, and income proof safely.\n"
        "- If there is domestic violence, dowry harassment, or threat, approach the police or relevant authority immediately.\n"
        "- Divorce, child-custody, and related matters may need to go to the Family Court or Police Station.\n\n"
        "If you want, I can break this down into where to file and documents needed for your family matter."
    )


def _workplace_issues_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Employment Issues",
        title_hi="नौकरी से जुड़ी समस्याएं",
        what_en="Collect emails and the offer letter, then raise an internal complaint.",
        where_en="Labour Court, or ICC for harassment complaints.",
        docs_en="Offer letter, salary slips, bank statement, and emails.",
        what_hi="ईमेल और ऑफर लेटर रखें, फिर कंपनी में शिकायत करें।",
        where_hi="लेबर कोर्ट, या उत्पीड़न के मामलों में ICC।",
        docs_hi="ऑफर लेटर, सैलरी स्लिप, बैंक स्टेटमेंट, और ईमेल।",
    )
    if lang == "hi":
        return (
            "- Offer letter, contract, salary slips, bank statements, HR emails, PF/ESI records और complaint copies संभालकर रखें.\n"
            "- Salary, termination, harassment, POSH, bond, या fake job मामलों में written proof बहुत महत्वपूर्ण है.\n"
            "- Labour issues Labour Court या labour authority में जा सकते हैं, और POSH मामलों में ICC/LCC का रास्ता भी होता है.\n\n"
            "अगर आप चाहें, तो मैं workplace issue के लिए exact forum और documents checklist दे सकता हूँ."
        )
    return (
        "- Keep the offer letter, salary slips, bank statement, and emails safely.\n"
        "- In salary-not-paid, wrongful-termination, or workplace-harassment matters, first raise an internal complaint.\n"
        "- Labour matters may go to the Labour Court, while harassment complaints can go to the ICC.\n\n"
        "If you want, I can give you the exact forum and document checklist for your workplace issue."
    )


def _domestic_violence_guidance(user_message: str, lang: str) -> str:
    lower = user_message.lower()
    asks_where = (
        "where" in lower
        or "file" in lower
        or "complaint" in lower
        or "report" in lower
        or "case" in lower
    )

    if lang == "hi":
        if asks_where:
            return (
                "- अगर तुरंत खतरा है, तो 181 या 112 पर अभी कॉल करें.\n"
                "- आप नजदीकी पुलिस स्टेशन में शिकायत या FIR दर्ज करा सकती हैं.\n"
                "- आप जिले के Protection Officer, महिला हेल्पलाइन, One Stop Centre, या Magistrate court के माध्यम से भी Domestic Violence Act के तहत राहत मांग सकती हैं.\n"
                "- मैसेज, फोटो, मेडिकल रिकॉर्ड, और गवाह की जानकारी सुरक्षित रखें.\n\n"
                "अगर आप चाहें, तो मैं घरेलू हिंसा शिकायत का draft भी तैयार करने में मदद कर सकता हूँ."
            )
        return (
            "- अगर तुरंत खतरा है, तो 181 या 112 पर अभी कॉल करें.\n"
            "- पुलिस, Protection Officer, या One Stop Centre से तुरंत मदद लें.\n"
            "- मैसेज, फोटो, मेडिकल रिकॉर्ड, और गवाह की जानकारी सुरक्षित रखें.\n\n"
            "अगर आप चाहें, तो मैं अगले कदम बहुत सरल भाषा में बता सकता हूँ."
        )

    if asks_where:
        return (
            "- If there is immediate danger, call 181 or 112 right away.\n"
            "- You can go to the nearest police station to file a complaint or FIR.\n"
            "- You can also approach the district Protection Officer, Women's Helpline, One Stop Centre, or the Magistrate court for relief under the Domestic Violence Act.\n"
            "- Keep messages, photos, medical records, and witness details safely.\n\n"
            "If you want, I can also help draft a domestic violence complaint."
        )
    return (
        "- If there is immediate danger, call 181 or 112 right away.\n"
        "- Reach out to the police, Protection Officer, or a One Stop Centre for help.\n"
        "- Keep messages, photos, medical records, and witness details safely.\n\n"
        "If you want, I can explain the next steps in simple language."
    )


def _cyber_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Cyber Crime",
        title_hi="साइबर अपराध",
        what_en="Report immediately and take screenshots.",
        where_en="Cyber Crime Portal or Police Station.",
        docs_en="Screenshots, transaction proof, bank statement, and emails.",
        what_hi="तुरंत रिपोर्ट करें और स्क्रीनशॉट लें।",
        where_hi="साइबर क्राइम पोर्टल या पुलिस स्टेशन।",
        docs_hi="स्क्रीनशॉट, लेन-देन का प्रमाण, बैंक स्टेटमेंट, और ईमेल।",
    )
    if lang == "hi":
        return (
            "- स्क्रीनशॉट, ट्रांजैक्शन आईडी, नंबर और लिंक सुरक्षित रखें.\n"
            "- cybercrime.gov.in पर रिपोर्ट करें या 1930 पर कॉल करें.\n"
            "- जरूरत हो तो पुलिस स्टेशन में FIR भी दर्ज करें."
        )
    return (
        "- Save screenshots, transaction IDs, phone numbers, and links.\n"
        "- Report quickly at cybercrime.gov.in or call 1930.\n"
        "- File an FIR at the police station as well if needed."
    )


def _consumer_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Consumer Complaints",
        title_hi="उपभोक्ता शिकायत",
        what_en="Keep the bill and contact the company first.",
        where_en="Consumer Court.",
        docs_en="Invoice or bill, payment proof, and screenshots.",
        what_hi="बिल रखें और पहले कंपनी से संपर्क करें।",
        where_hi="कंज्यूमर कोर्ट।",
        docs_hi="बिल, पेमेंट प्रूफ, और स्क्रीनशॉट।",
    )
    if lang == "hi":
        return (
            "- बिल, वारंटी और विक्रेता से हुई बात सुरक्षित रखें.\n"
            "- पहले लिखित में refund या replacement माँगें.\n"
            "- समाधान न मिले तो eDaakhil या जिला उपभोक्ता फोरम में शिकायत करें."
        )
    return (
        "- Keep the bill, warranty, and seller communication safely.\n"
        "- First ask for a refund or replacement in writing.\n"
        "- If unresolved, file a complaint on eDaakhil or before the District Consumer Forum."
    )


def _traffic_public_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Traffic Issues",
        title_hi="ट्रैफिक मामले",
        what_en="Gather evidence and contact the police.",
        where_en="Traffic Police or MACT Tribunal.",
        docs_en="Driving license, RC, insurance, and FIR.",
        what_hi="सबूत इकट्ठा करें और पुलिस से संपर्क करें।",
        where_hi="ट्रैफिक पुलिस या MACT ट्रिब्यूनल।",
        docs_hi="ड्राइविंग लाइसेंस, आरसी, इंश्योरेंस, और एफआईआर।",
    )
    if lang == "hi":
        return (
            "- Driving licence, RC, insurance, challan/FIR, फोटो, मेडिकल रिकॉर्ड और repair bills सुरक्षित रखें.\n"
            "- Accident, hit and run, vehicle theft, या public nuisance मामलों में पुलिस को जल्दी सूचना दें.\n"
            "- Compensation या insurance dispute के लिए MACT, insurer, या traffic authority के सामने जाना पड़ सकता है.\n\n"
            "अगर आप चाहें, तो मैं traffic या accident matter के लिए step-by-step प्रक्रिया बता सकता हूँ."
        )
    return (
        "- Keep the driving license, RC, insurance, and FIR safely.\n"
        "- Gather evidence and contact the police quickly in accident, vehicle-theft, or insurance-claim matters.\n"
        "- The matter may need to go before the Traffic Police or MACT Tribunal.\n\n"
        "If you want, I can explain the traffic or accident process step by step."
    )


def _financial_banking_guidance(user_message: str, lang: str) -> str:
    return _compose_topic_guidance(
        user_message=user_message,
        lang=lang,
        title_en="Financial Issues",
        title_hi="बैंकिंग और वित्तीय मामले",
        what_en="Inform the bank immediately and keep proof.",
        where_en="RBI Ombudsman or Police.",
        docs_en="Bank statement, cheque plus memo, and loan documents.",
        what_hi="तुरंत बैंक को बताएं और सबूत सुरक्षित रखें।",
        where_hi="RBI ओम्बड्समैन या पुलिस।",
        docs_hi="बैंक स्टेटमेंट, चेक और मेमो, और लोन दस्तावेज।",
    )
    if lang == "hi":
        return (
            "- बैंक statements, transaction proof, loan papers, cheque copy, bounce memo, SMS/email records, और policy papers सुरक्षित रखें.\n"
            "- Fraud या unauthorized transaction में तुरंत bank को inform करें और जरूरत हो तो police/cyber complaint करें.\n"
            "- Bank grievance, RBI Ombudsman, civil court, या cheque bounce process अलग-अलग मामलों में उपयोगी हो सकते हैं.\n\n"
            "अगर आप चाहें, तो मैं banking या financial issue के लिए सही forum और documents checklist दे सकता हूँ."
        )
    return (
        "- Keep the bank statement, cheque + memo, and loan documents safely.\n"
        "- In bank-fraud, cheque-bounce, or loan-harassment matters, inform the bank immediately and preserve proof.\n"
        "- Depending on the dispute, you may need the RBI Ombudsman or the police.\n\n"
        "If you want, I can give you the right forum and documents checklist for your banking or financial issue."
    )


def _legal_aid_guidance(lang: str) -> str:
    if lang == "hi":
        return (
            "- अपने जिले के DLSA से संपर्क करें.\n"
            "- NALSA हेल्पलाइन 15100 पर कॉल करें.\n"
            "- अपनी ID और केस के basic papers साथ रखें."
        )
    return (
        "- Contact the District Legal Services Authority in your district.\n"
        "- Call NALSA helpline 15100.\n"
        "- Keep your ID and basic case papers ready."
    )


def _constitutional_rights_guidance(lang: str) -> str:
    if lang == "hi":
        return (
            "- अनुच्छेद 14: कानून के सामने समानता.\n"
            "- अनुच्छेद 19: बोलने, शांतिपूर्ण सभा, संघ बनाने, आने-जाने, रहने और पेशा चुनने जैसी स्वतंत्रताएँ, उचित कानूनी प्रतिबंधों के अधीन.\n"
            "- अनुच्छेद 21: जीवन और व्यक्तिगत स्वतंत्रता का संरक्षण.\n"
            "- अनुच्छेद 22: गिरफ्तारी के कारण बताने, वकील से मिलने और सामान्यतः 24 घंटे में मजिस्ट्रेट के सामने पेश किए जाने का अधिकार.\n"
            "- अनुच्छेद 32: Fundamental Rights लागू कराने के लिए Supreme Court जाने का अधिकार."
        )
    return (
        "- Article 14: equality before law.\n"
        "- Article 19: freedoms like speech, peaceful assembly, association, movement, residence, and profession, subject to reasonable restrictions.\n"
        "- Article 21: protection of life and personal liberty.\n"
        "- Article 22: important arrest protections, including being told the grounds of arrest, consulting a lawyer, and usually being produced before a magistrate within 24 hours.\n"
        "- Article 32: the right to approach the Supreme Court to enforce Fundamental Rights."
    )


def _criminal_law_basics_guidance(lang: str) -> str:
    if lang == "hi":
        return (
            "- भारत का मुख्य आपराधिक कानून अब Bharatiya Nyaya Sanhita, 2023 है, जो 1 जुलाई 2024 से लागू है.\n"
            "- लोग अभी भी रोज़मर्रा की भाषा में IPC बोलते हैं, इसलिए दोनों नाम समझना उपयोगी है.\n"
            "- चोरी, डकैती/लूट, उगाही, हमला, wrongful restraint और self-defence जैसे बुनियादी विषय इसी कानून में आते हैं.\n"
            "- अगर आप चाहें, तो मैं किसी एक अपराध को बहुत सरल भाषा में अलग से समझा सकता हूँ."
        )
    return (
        "- India's main criminal law is now the Bharatiya Nyaya Sanhita, 2023, in force from July 1, 2024.\n"
        "- Many people still say IPC in everyday conversation, so it helps to understand both the older and current terminology.\n"
        "- Basic topics like theft, robbery, extortion, assault, wrongful restraint, and private defence are covered there.\n"
        "- If you want, I can explain any one of these offences in very simple language."
    )


def _is_vague_question(user_message: str) -> bool:
    if _looks_like_theft_or_fir_query(user_message.lower()):
        return False
    tokens = re.findall(r"\w+", user_message.lower())
    if len(tokens) <= 4:
        return True
    vague_phrases = {
        "help",
        "legal help",
        "need help",
        "how to file case",
        "case",
        "problem",
        "issue",
    }
    compact = " ".join(tokens[:4])
    return user_message.lower().strip() in vague_phrases or compact in vague_phrases


def _generic_guidance(lang: str) -> str:
    if lang == "hi":
        return (
            "मैं आपकी कानूनी समस्या समझने में मदद कर सकता हूँ। कृपया अपनी समस्या विस्तार से बताएँ:\n\n"
            "- **चोरी / एफ़आईआर** — चोरी, डकैती, एफ़आईआर प्रक्रिया\n"
            "- **घरेलू हिंसा** — शारीरिक, मानसिक, आर्थिक शोषण\n"
            "- **वेतन चोरी** — वेतन न मिलना, न्यूनतम वेतन\n"
            "- **भूमि विवाद** — सम्पत्ति, ज़मीन, अतिक्रमण\n"
            "- **साइबर अपराध** — ऑनलाइन धोखाधड़ी, हैकिंग\n"
            "- **उपभोक्ता अधिकार** — खराब उत्पाद, रिफ़ंड\n\n"
            "आपातकाल में: पुलिस **100** | महिला **181** | आपातकाल **112**"
        )
    return (
        "I can help you understand your legal rights. Please describe your issue in detail:\n\n"
        "- **Theft / FIR** — stolen property, robbery, FIR process\n"
        "- **Domestic Violence** — physical, emotional, economic abuse\n"
        "- **Wage Theft** — unpaid wages, minimum wage violations\n"
        "- **Land Dispute** — property, encroachment, ownership\n"
        "- **Cyber Crime** — online fraud, hacking, identity theft\n"
        "- **Consumer Rights** — defective products, refunds\n\n"
        "Emergency: Police **100** | Women **181** | Emergency **112**"
    )


def _resolve_response_language(requested_lang: str, detected_lang: str) -> str:
    if requested_lang in SUPPORTED_LANGUAGES:
        return requested_lang
    return detected_lang if detected_lang in SUPPORTED_LANGUAGES else "en"


def _localize_topic_label(topic: str, lang: str) -> str:
    if lang != "hi":
        return TOPIC_LABELS.get(topic, topic.replace("_", " "))

    hi_labels = {
        "theft": "चोरी",
        "theft_complaint": "चोरी",
        "fir_process": "एफआईआर प्रक्रिया",
        "property_rent": "संपत्ति और किराया विवाद",
        "family_personal": "पारिवारिक और व्यक्तिगत मामले",
        "workplace_issues": "नौकरी और कार्यस्थल के मामले",
        "domestic_violence": "घरेलू हिंसा",
        "harassment": "उत्पीड़न",
        "wage_theft": "वेतन विवाद",
        "land_dispute": "भूमि विवाद",
        "cyber_crime": "साइबर अपराध",
        "consumer_rights": "उपभोक्ता अधिकार",
        "traffic_public": "यातायात और सार्वजनिक मामले",
        "financial_banking": "बैंकिंग और वित्तीय मामले",
        "legal_aid": "निःशुल्क कानूनी सहायता",
        "rti": "आरटीआई",
        "child_rights": "बाल अधिकार",
        "constitutional_rights": "संवैधानिक अधिकार",
        "criminal_law_basics": "आपराधिक कानून की मूल बातें",
        "general_legal_query": "कानूनी समस्या",
    }
    return hi_labels.get(topic, topic.replace("_", " "))


def _contains_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097F" for ch in text)


def _localize_legal_text(text: str, lang: str) -> str:
    if lang != "hi" or _contains_devanagari(text):
        return text
    return _translate_legal_english_to_hindi(text)


def _translate_legal_english_to_hindi(text: str) -> str:
    translated = text.strip()
    replacements = [
        ("If someone illegally occupies your land or property, file a complaint at the local police station or approach the Revenue Court (Tehsildar).",
         "यदि कोई आपकी भूमि या संपत्ति पर अवैध कब्जा कर ले, तो स्थानीय पुलिस स्टेशन में शिकायत करें या राजस्व न्यायालय (तहसीलदार) से संपर्क करें।"),
        ("Keep all documents like sale deed, property tax receipts, and Aadhaar-linked land records as evidence.",
         "बिक्री विलेख, संपत्ति कर रसीदें और आधार से जुड़े भूमि रिकॉर्ड जैसे दस्तावेज सबूत के रूप में सुरक्षित रखें।"),
        ("You can also file a civil suit for possession.",
         "आप कब्जा वापस पाने के लिए सिविल मुकदमा भी दायर कर सकते हैं।"),
        ("To file an FIR for theft, provide: what was stolen, when it happened, where it happened, and any details about the suspect.",
         "चोरी की एफआईआर के लिए बताएं: क्या चोरी हुआ, कब हुआ, कहाँ हुआ, और आरोपी के बारे में जो भी जानकारी हो।"),
        ("You can also file an e-FIR online in many states.",
         "कई राज्यों में आप ऑनलाइन ई-एफआईआर भी दर्ज कर सकते हैं।"),
        ("If police refuse to register your FIR, complain to the Superintendent of Police or file a complaint in court under Section 156(3) CrPC.",
         "अगर पुलिस एफआईआर दर्ज करने से मना करे, तो पुलिस अधीक्षक से शिकायत करें या धारा 156(3) सीआरपीसी के तहत अदालत में आवेदन दें।"),
        ("An FIR (First Information Report) is the first step in reporting a crime.",
         "एफआईआर (प्रथम सूचना रिपोर्ट) अपराध की रिपोर्ट करने का पहला कदम है।"),
        ("Save screenshots, transaction IDs, phone numbers, and links.",
         "स्क्रीनशॉट, ट्रांजैक्शन आईडी, फोन नंबर और लिंक सुरक्षित रखें।"),
        ("Report quickly at cybercrime.gov.in or call 1930.",
         "जल्दी से cybercrime.gov.in पर शिकायत करें या 1930 पर कॉल करें।"),
        ("If money was lost, also file an FIR or police complaint.",
         "अगर पैसे गए हैं, तो एफआईआर या पुलिस शिकायत भी दर्ज करें।"),
        ("Keep the bill, warranty, and seller communication safely.",
         "बिल, वारंटी और विक्रेता से हुई बातचीत सुरक्षित रखें।"),
        ("First ask for a refund or replacement in writing.",
         "पहले लिखित रूप में रिफंड या रिप्लेसमेंट मांगें।"),
        ("If unresolved, file a complaint on eDaakhil or before the District Consumer Forum.",
         "समाधान न मिलने पर eDaakhil या जिला उपभोक्ता फोरम में शिकायत करें।"),
        ("Every worker has the right to receive their full wages on time under the Payment of Wages Act.",
         "à¤¹à¤° à¤•à¤°à¥à¤®à¤šà¤¾à¤°à¥€ à¤•à¥‹ Payment of Wages Act à¤•à¥‡ à¤¤à¤¹à¤¤ à¤¸à¤®à¤¯ à¤ªà¤° à¤ªà¥‚à¤°à¤¾ à¤µà¥‡à¤¤à¤¨ à¤ªà¤¾à¤¨à¥‡ à¤•à¤¾ à¤…à¤§à¤¿à¤•à¤¾à¤° à¤¹à¥ˆà¥¤"),
        ("If your employer withholds your salary, file a complaint with the Labour Commissioner in your district.",
         "à¤…à¤—à¤° à¤†à¤ªà¤•à¥‡ à¤¨à¤¿à¤¯à¥‹à¤•à¥à¤¤à¤¾ à¤¨à¥‡ à¤µà¥‡à¤¤à¤¨ à¤°à¥‹à¤• à¤²à¤¿à¤¯à¤¾ à¤¹à¥ˆ, à¤¤à¥‹ à¤…à¤ªà¤¨à¥‡ à¤œà¤¿à¤²à¥‡ à¤•à¥‡ Labour Commissioner à¤•à¥‡ à¤ªà¤¾à¤¸ à¤¶à¤¿à¤•à¤¾à¤¯à¤¤ à¤•à¤°à¥‡à¤‚à¥¤"),
        ("This is free and you do not need a lawyer.",
         "à¤¯à¤¹ à¤ªà¥à¤°à¤•à¥à¤°à¤¿à¤¯à¤¾ à¤®à¥à¤«à¥à¤¤ à¤¹à¥ˆ à¤”à¤° à¤‡à¤¸à¤•à¥‡ à¤²à¤¿à¤ à¤µà¤•à¥€à¤² à¤•à¥€ à¤œà¤°à¥‚à¤°à¤¤ à¤¨à¤¹à¥€à¤‚ à¤¹à¥ˆà¥¤"),
        ("Migrant workers have the same rights as local workers.",
         "à¤ªà¥à¤°à¤µà¤¾à¤¸à¥€ à¤®à¤œà¤¦à¥‚à¤°à¥‹à¤‚ à¤•à¥‹ à¤­à¥€ à¤¸à¥à¤¥à¤¾à¤¨à¥€à¤¯ à¤®à¤œà¤¦à¥‚à¤°à¥‹à¤‚ à¤œà¥ˆà¤¸à¥‡ à¤¹à¥€ à¤…à¤§à¤¿à¤•à¤¾à¤° à¤®à¤¿à¤²à¤¤à¥‡ à¤¹à¥ˆà¤‚à¥¤"),
    ]

    for src, dest in replacements:
        translated = translated.replace(src, dest)

    generic_terms = [
        ("land dispute", "भूमि विवाद"),
        ("property and rent issues", "संपत्ति और किराया विवाद"),
        ("property", "संपत्ति"),
        ("land", "भूमि"),
        ("complaint", "शिकायत"),
        ("police station", "पुलिस स्टेशन"),
        ("civil suit", "सिविल मुकदमा"),
        ("evidence", "सबूत"),
        ("documents", "दस्तावेज"),
        ("Consumer Court", "उपभोक्ता न्यायालय"),
        ("Civil Court", "सिविल कोर्ट"),
        ("Rent Tribunal", "किराया न्यायाधिकरण"),
    ]
    for src, dest in generic_terms:
        translated = re.sub(rf"\b{re.escape(src)}\b", dest, translated, flags=re.IGNORECASE)
    return translated


def _translate_legal_english_to_hindi(text: str) -> str:
    translated = text.strip()
    replacements = [
        (
            "If someone illegally occupies your land or property, file a complaint at the local police station or approach the Revenue Court (Tehsildar).",
            "\u092f\u0926\u093f \u0915\u094b\u0908 \u0906\u092a\u0915\u0940 \u092d\u0942\u092e\u093f \u092f\u093e \u0938\u0902\u092a\u0924\u094d\u0924\u093f \u092a\u0930 \u0905\u0935\u0948\u0927 \u0915\u092c\u094d\u091c\u093e \u0915\u0930 \u0932\u0947, \u0924\u094b \u0938\u094d\u0925\u093e\u0928\u0940\u092f \u092a\u0941\u0932\u093f\u0938 \u0938\u094d\u091f\u0947\u0936\u0928 \u092e\u0947\u0902 \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0930\u0947\u0902 \u092f\u093e \u0930\u093e\u091c\u0938\u094d\u0935 \u0928\u094d\u092f\u093e\u092f\u093e\u0932\u092f (\u0924\u0939\u0938\u0940\u0932\u0926\u093e\u0930) \u0938\u0947 \u0938\u0902\u092a\u0930\u094d\u0915 \u0915\u0930\u0947\u0902\u0964",
        ),
        (
            "Keep all documents like sale deed, property tax receipts, and Aadhaar-linked land records as evidence.",
            "\u092c\u093f\u0915\u094d\u0930\u0940 \u0935\u093f\u0932\u0947\u0916, \u0938\u0902\u092a\u0924\u094d\u0924\u093f \u0915\u0930 \u0930\u0938\u0940\u0926\u0947\u0902 \u0914\u0930 \u0906\u0927\u093e\u0930 \u0938\u0947 \u091c\u0941\u0921\u093c\u0947 \u092d\u0942\u092e\u093f \u0930\u093f\u0915\u0949\u0930\u094d\u0921 \u091c\u0948\u0938\u0947 \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c \u0938\u092c\u0942\u0924 \u0915\u0947 \u0930\u0942\u092a \u092e\u0947\u0902 \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924 \u0930\u0916\u0947\u0902\u0964",
        ),
        (
            "You can also file a civil suit for possession.",
            "\u0906\u092a \u0915\u092c\u094d\u091c\u093e \u0935\u093e\u092a\u0938 \u092a\u093e\u0928\u0947 \u0915\u0947 \u0932\u093f\u090f \u0938\u093f\u0935\u093f\u0932 \u092e\u0941\u0915\u0926\u092e\u093e \u092d\u0940 \u0926\u093e\u092f\u0930 \u0915\u0930 \u0938\u0915\u0924\u0947 \u0939\u0948\u0902\u0964",
        ),
        (
            "To file an FIR for theft, provide: what was stolen, when it happened, where it happened, and any details about the suspect.",
            "\u091a\u094b\u0930\u0940 \u0915\u0940 \u090f\u092b\u0906\u0908\u0906\u0930 \u0915\u0947 \u0932\u093f\u090f \u092c\u0924\u093e\u090f\u0902: \u0915\u094d\u092f\u093e \u091a\u094b\u0930\u0940 \u0939\u0941\u0908, \u0915\u092c \u0939\u0941\u0908, \u0915\u0939\u093e\u0901 \u0939\u0941\u0908, \u0914\u0930 \u0906\u0930\u094b\u092a\u0940 \u0915\u0947 \u092c\u093e\u0930\u0947 \u092e\u0947\u0902 \u091c\u094b \u092d\u0940 \u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0939\u094b\u0964",
        ),
        (
            "You can also file an e-FIR online in many states.",
            "\u0915\u0908 \u0930\u093e\u091c\u094d\u092f\u094b\u0902 \u092e\u0947\u0902 \u0906\u092a \u0911\u0928\u0932\u093e\u0907\u0928 \u0908-\u090f\u092b\u0906\u0908\u0906\u0930 \u092d\u0940 \u0926\u0930\u094d\u091c \u0915\u0930 \u0938\u0915\u0924\u0947 \u0939\u0948\u0902\u0964",
        ),
        (
            "If police refuse to register your FIR, complain to the Superintendent of Police or file a complaint in court under Section 156(3) CrPC.",
            "\u0905\u0917\u0930 \u092a\u0941\u0932\u093f\u0938 \u090f\u092b\u0906\u0908\u0906\u0930 \u0926\u0930\u094d\u091c \u0915\u0930\u0928\u0947 \u0938\u0947 \u092e\u0928\u093e \u0915\u0930\u0947, \u0924\u094b \u092a\u0941\u0932\u093f\u0938 \u0905\u0927\u0940\u0915\u094d\u0937\u0915 \u0938\u0947 \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0930\u0947\u0902 \u092f\u093e \u0927\u093e\u0930\u093e 156(3) \u0938\u0940\u0906\u0930\u092a\u0940\u0938\u0940 \u0915\u0947 \u0924\u0939\u0924 \u0905\u0926\u093e\u0932\u0924 \u092e\u0947\u0902 \u0906\u0935\u0947\u0926\u0928 \u0926\u0947\u0902\u0964",
        ),
        (
            "An FIR (First Information Report) is the first step in reporting a crime.",
            "\u090f\u092b\u0906\u0908\u0906\u0930 (\u092a\u094d\u0930\u0925\u092e \u0938\u0942\u091a\u0928\u093e \u0930\u093f\u092a\u094b\u0930\u094d\u091f) \u0905\u092a\u0930\u093e\u0927 \u0915\u0940 \u0930\u093f\u092a\u094b\u0930\u094d\u091f \u0915\u0930\u0928\u0947 \u0915\u093e \u092a\u0939\u0932\u093e \u0915\u0926\u092e \u0939\u0948\u0964",
        ),
        (
            "Save screenshots, transaction IDs, phone numbers, and links.",
            "\u0938\u094d\u0915\u094d\u0930\u0940\u0928\u0936\u0949\u091f, \u091f\u094d\u0930\u093e\u0902\u091c\u0948\u0915\u094d\u0936\u0928 \u0906\u0908\u0921\u0940, \u092b\u094b\u0928 \u0928\u0902\u092c\u0930 \u0914\u0930 \u0932\u093f\u0902\u0915 \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924 \u0930\u0916\u0947\u0902\u0964",
        ),
        (
            "Report quickly at cybercrime.gov.in or call 1930.",
            "\u091c\u0932\u094d\u0926\u0940 \u0938\u0947 cybercrime.gov.in \u092a\u0930 \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0930\u0947\u0902 \u092f\u093e 1930 \u092a\u0930 \u0915\u0949\u0932 \u0915\u0930\u0947\u0902\u0964",
        ),
        (
            "If money was lost, also file an FIR or police complaint.",
            "\u0905\u0917\u0930 \u092a\u0948\u0938\u0947 \u0917\u090f \u0939\u0948\u0902, \u0924\u094b \u090f\u092b\u0906\u0908\u0906\u0930 \u092f\u093e \u092a\u0941\u0932\u093f\u0938 \u0936\u093f\u0915\u093e\u092f\u0924 \u092d\u0940 \u0926\u0930\u094d\u091c \u0915\u0930\u0947\u0902\u0964",
        ),
        (
            "Keep the bill, warranty, and seller communication safely.",
            "\u092c\u093f\u0932, \u0935\u093e\u0930\u0902\u091f\u0940 \u0914\u0930 \u0935\u093f\u0915\u094d\u0930\u0947\u0924\u093e \u0938\u0947 \u0939\u0941\u0908 \u092c\u093e\u0924\u091a\u0940\u0924 \u0938\u0941\u0930\u0915\u094d\u0937\u093f\u0924 \u0930\u0916\u0947\u0902\u0964",
        ),
        (
            "First ask for a refund or replacement in writing.",
            "\u092a\u0939\u0932\u0947 \u0932\u093f\u0916\u093f\u0924 \u0930\u0942\u092a \u092e\u0947\u0902 \u0930\u093f\u092b\u0902\u0921 \u092f\u093e \u0930\u093f\u092a\u094d\u0932\u0947\u0938\u092e\u0947\u0902\u091f \u092e\u093e\u0902\u0917\u0947\u0902\u0964",
        ),
        (
            "If unresolved, file a complaint on eDaakhil or before the District Consumer Forum.",
            "\u0938\u092e\u093e\u0927\u093e\u0928 \u0928 \u092e\u093f\u0932\u0928\u0947 \u092a\u0930 eDaakhil \u092f\u093e \u091c\u093f\u0932\u093e \u0909\u092a\u092d\u094b\u0915\u094d\u0924\u093e \u092b\u094b\u0930\u092e \u092e\u0947\u0902 \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0930\u0947\u0902\u0964",
        ),
        (
            "Every worker has the right to receive their full wages on time under the Payment of Wages Act.",
            "\u0939\u0930 \u0915\u0930\u094d\u092e\u091a\u093e\u0930\u0940 \u0915\u094b Payment of Wages Act \u0915\u0947 \u0924\u0939\u0924 \u0938\u092e\u092f \u092a\u0930 \u092a\u0942\u0930\u093e \u0935\u0947\u0924\u0928 \u092a\u093e\u0928\u0947 \u0915\u093e \u0905\u0927\u093f\u0915\u093e\u0930 \u0939\u0948\u0964",
        ),
        (
            "If your employer withholds your salary, file a complaint with the Labour Commissioner in your district.",
            "\u0905\u0917\u0930 \u0906\u092a\u0915\u0947 \u0928\u093f\u092f\u094b\u0915\u094d\u0924\u093e \u0928\u0947 \u0935\u0947\u0924\u0928 \u0930\u094b\u0915 \u0932\u093f\u092f\u093e \u0939\u0948, \u0924\u094b \u0905\u092a\u0928\u0947 \u091c\u093f\u0932\u0947 \u0915\u0947 Labour Commissioner \u0915\u0947 \u092a\u093e\u0938 \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0930\u0947\u0902\u0964",
        ),
        (
            "This is free and you do not need a lawyer.",
            "\u092f\u0939 \u092a\u094d\u0930\u0915\u094d\u0930\u093f\u092f\u093e \u092e\u0941\u092b\u094d\u0924 \u0939\u0948 \u0914\u0930 \u0907\u0938\u0915\u0947 \u0932\u093f\u090f \u0935\u0915\u0940\u0932 \u0915\u0940 \u091c\u0930\u0942\u0930\u0924 \u0928\u0939\u0940\u0902 \u0939\u0948\u0964",
        ),
        (
            "Migrant workers have the same rights as local workers.",
            "\u092a\u094d\u0930\u0935\u093e\u0938\u0940 \u092e\u091c\u0926\u0942\u0930\u094b\u0902 \u0915\u094b \u092d\u0940 \u0938\u094d\u0925\u093e\u0928\u0940\u092f \u092e\u091c\u0926\u0942\u0930\u094b\u0902 \u091c\u0948\u0938\u0947 \u0939\u0940 \u0905\u0927\u093f\u0915\u093e\u0930 \u092e\u093f\u0932\u0924\u0947 \u0939\u0948\u0902\u0964",
        ),
    ]

    for src, dest in replacements:
        translated = translated.replace(src, dest)

    generic_terms = [
        ("land dispute", "\u092d\u0942\u092e\u093f \u0935\u093f\u0935\u093e\u0926"),
        ("property and rent issues", "\u0938\u0902\u092a\u0924\u094d\u0924\u093f \u0914\u0930 \u0915\u093f\u0930\u093e\u092f\u093e \u0935\u093f\u0935\u093e\u0926"),
        ("property", "\u0938\u0902\u092a\u0924\u094d\u0924\u093f"),
        ("land", "\u092d\u0942\u092e\u093f"),
        ("complaint", "\u0936\u093f\u0915\u093e\u092f\u0924"),
        ("police station", "\u092a\u0941\u0932\u093f\u0938 \u0938\u094d\u091f\u0947\u0936\u0928"),
        ("civil suit", "\u0938\u093f\u0935\u093f\u0932 \u092e\u0941\u0915\u0926\u092e\u093e"),
        ("evidence", "\u0938\u092c\u0942\u0924"),
        ("documents", "\u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c"),
        ("Consumer Court", "\u0909\u092a\u092d\u094b\u0915\u094d\u0924\u093e \u0928\u094d\u092f\u093e\u092f\u093e\u0932\u092f"),
        ("Civil Court", "\u0938\u093f\u0935\u093f\u0932 \u0915\u094b\u0930\u094d\u091f"),
        ("Rent Tribunal", "\u0915\u093f\u0930\u093e\u092f\u093e \u0928\u094d\u092f\u093e\u092f\u093e\u0927\u093f\u0915\u0930\u0923"),
    ]
    for src, dest in generic_terms:
        translated = re.sub(rf"\b{re.escape(src)}\b", dest, translated, flags=re.IGNORECASE)
    return translated


def _format_memory_note(memories: list, lang: str) -> str:
    if lang == "hi":
        note = "*(पिछले सत्रों से:*"
    else:
        note = "*(From your previous sessions:*"
    for m in memories[:2]:
        case = m["case_type"].replace("_", " ").title()
        note += f" *{case}*,"
    note = note.rstrip(",") + "*)*"
    return note


def _should_include_memory_note(intent: str, conversation: list) -> bool:
    return bool(conversation) or intent != "general_legal_query"


def _looks_like_theft_or_fir_query(lower: str) -> bool:
    has_where_to_go = ("where to go" in lower) or ("where do i go" in lower) or ("kaha" in lower and "jana" in lower)
    has_reporting = (
        "file report" in lower
        or "report" in lower
        or "file complaint" in lower
        or "complaint" in lower
        or "fir" in lower
    )
    has_missing_property = any(
        phrase in lower
        for phrase in (
            "missing gold",
            "gold missing",
            "missing jewellery",
            "missing jewelry",
            "stolen gold",
            "stolen jewellery",
            "stolen jewelry",
            "gold chain",
            "ring",
            "necklace",
            "wallet",
            "phone",
            "jewellery",
            "jewelry",
            "stolen",
            "theft",
            "chori",
        )
    )
    return (has_reporting and has_missing_property) or (has_where_to_go and has_missing_property)


def _looks_like_rent_deposit_query(lower: str) -> bool:
    landlord_terms = ("landlord", "owner", "tenant", "rent agreement", "lease", "rental")
    deposit_terms = ("deposit", "security deposit", "refund", "advance", "not returning", "deduct", "deduction")
    rent_terms = ("rent", "vacate", "move out", "handover", "rented house", "flat")
    has_landlord_context = any(term in lower for term in landlord_terms)
    has_deposit_context = any(term in lower for term in deposit_terms)
    has_rent_context = any(term in lower for term in rent_terms)
    return has_deposit_context and (has_landlord_context or has_rent_context)


def _normalize_reply(reply: str, lang: str) -> str:
    text = (reply or "").strip()
    disclaimer_patterns = [
        r"\*?Please note: I provide general legal information only\.[^\n]*\*?",
        r"\*?Please note: This is general legal information only\.[^\n]*\*?",
        r"\*?For specific legal advice, please consult a qualified lawyer\.\*?",
        r"\*?कृपया ध्यान दें:[^\n]*\*?",
    ]

    for pattern in disclaimer_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n\n" + _disclaimer(lang)


def _disclaimer(lang: str) -> str:
    if lang == "hi":
        return "*कृपया ध्यान दें: यह केवल सामान्य कानूनी जानकारी है। विशिष्ट सलाह के लिए योग्य वकील से परामर्श करें।*"
    return "*Please note: This is general legal information only. For specific legal advice, please consult a qualified lawyer.*"


def generate_document_content(doc_type: str, details: dict) -> str:
    """Generate document text using templates (no LLM needed)."""
    complainant = details.get("complainant_name", details.get("complainant_id", "The Complainant"))
    incident = details.get("incident_description", "As described verbally")
    date_time = details.get("date_time", "Date not specified")
    location = details.get("location", "Location not specified")
    suspect = details.get("suspect_description", "Unknown")
    witness = details.get("witness", "None provided")
    language = str(details.get("language", "en")).lower()

    if doc_type == "FIR":
        if language == "hi":
            return _fir_template_hi(complainant, incident, date_time, location, suspect, witness)
        return _fir_template(complainant, incident, date_time, location, suspect, witness)
    elif "Domestic Violence" in doc_type:
        return _dv_template(complainant, incident, date_time, location, suspect)
    elif "Labour" in doc_type or "Wage" in doc_type:
        return _labour_template(complainant, incident, date_time, location, details)
    else:
        return _generic_complaint_template(doc_type, complainant, incident, date_time, location, suspect, details)


def _fir_template(complainant, incident, date_time, location, suspect, witness):
    return f"""FIRST INFORMATION REPORT (FIR)

To,
The Station House Officer,
[Nearest Police Station]

Subject: Request for Registration of First Information Report

Respected Sir/Madam,

I, {complainant}, hereby wish to lodge a First Information Report regarding the following incident:

INCIDENT DETAILS:
{incident}

DATE AND TIME: {date_time}
PLACE OF OCCURRENCE: {location}

SUSPECT DESCRIPTION:
{suspect}

WITNESSES:
{witness}

I request that this FIR be registered under the appropriate sections of the Indian Penal Code and that necessary investigation be carried out at the earliest.

I declare that the facts stated above are true to the best of my knowledge and belief.

Yours faithfully,
{complainant}

Note: Under Section 154 of CrPC, the police are legally bound to register this FIR. Refusal to do so is punishable under Section 166A IPC with imprisonment up to 2 years.
"""


def _fir_template_hi(complainant, incident, date_time, location, suspect, witness):
    return f"""प्रथम सूचना रिपोर्ट (एफआईआर)

सेवा में,
स्टेशन हाउस ऑफिसर,
[निकटतम पुलिस थाना]

विषय: प्रथम सूचना रिपोर्ट दर्ज करने हेतु प्रार्थना पत्र

महोदय / महोदया,

मैं, {complainant}, निम्नलिखित घटना के संबंध में प्राथमिकी दर्ज कराना चाहता/चाहती हूँ:

घटना का विवरण:
{incident}

दिनांक और समय: {date_time}
घटना का स्थान: {location}

आरोपी का विवरण:
{suspect}

गवाह:
{witness}

कृपया इस प्राथमिकी को भारतीय दंड संहिता की उपयुक्त धाराओं के अंतर्गत दर्ज कर आवश्यक जांच शीघ्र प्रारंभ करने की कृपा करें।

मैं घोषित करता/करती हूँ कि ऊपर लिखे गए तथ्य मेरी जानकारी और विश्वास के अनुसार सत्य हैं।

भवदीय,
{complainant}

नोट: दंड प्रक्रिया संहिता की धारा 154 के अंतर्गत पुलिस आपके एफआईआर को दर्ज करने के लिए बाध्य है। एफआईआर दर्ज करने से मना करना भारतीय दंड संहिता की धारा 166A के अंतर्गत दंडनीय है।
"""


def _dv_template(complainant, incident, date_time, location, suspect):
    return f"""COMPLAINT UNDER THE PROTECTION OF WOMEN FROM DOMESTIC VIOLENCE ACT, 2005

To,
The Protection Officer / Magistrate,
[Jurisdiction]

Subject: Complaint of Domestic Violence

Respected Sir/Madam,

I, {complainant}, hereby submit this complaint under the Protection of Women from Domestic Violence Act, 2005.

DETAILS OF VIOLENCE:
{incident}

DATE: {date_time}
ADDRESS WHERE VIOLENCE OCCURRED: {location}
RESPONDENT (ACCUSED): {suspect}

RELIEF SOUGHT:
1. Protection Order under Section 18 of the DV Act
2. Residence Order under Section 19
3. Monetary Relief under Section 20
4. Any other relief the Hon'ble Court deems fit

I request immediate action and protection as per law.

{complainant}

Emergency Contacts: Women Helpline 181 | Police 100 | Emergency 112
"""


def _labour_template(complainant, incident, date_time, location, details):
    employer = details.get("employer_name", "The Employer")
    amount = details.get("amount_due", "Amount not specified")
    return f"""COMPLAINT TO THE LABOUR COMMISSIONER

To,
The Labour Commissioner,
[District/State]

Subject: Complaint Regarding Non-Payment of Wages / Labour Dispute

Respected Sir/Madam,

I, {complainant}, hereby file this complaint under the Payment of Wages Act, 1936 and the Minimum Wages Act, 1948.

DETAILS:
{incident}

EMPLOYER: {employer}
AMOUNT DUE: {amount}
PERIOD: {date_time}
WORKPLACE ADDRESS: {location}

I request that appropriate action be taken against the employer as per the provisions of the law.

{complainant}

Note: Filing this complaint is free. No lawyer is required. Contact NALSA Helpline 15100 for free legal aid.
"""


def _generic_complaint_template(doc_type, complainant, incident, date_time, location, suspect, details):
    return f"""{doc_type.upper()}

To,
The Appropriate Authority,
[Jurisdiction]

Subject: {doc_type}

Respected Sir/Madam,

I, {complainant}, hereby submit this {doc_type} regarding the following matter:

DETAILS:
{incident}

DATE: {date_time}
LOCATION: {location}
ACCUSED / RESPONDENT: {suspect}

I request that appropriate action be taken as per the provisions of law.

{complainant}

Disclaimer: This document was generated by NyayaVoice AI assistant for informational purposes. Please review with a legal professional before submission.
"""
