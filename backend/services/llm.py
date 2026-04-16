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

from backend.config import SUPPORTED_LANGUAGES, EMERGENCY_KEYWORDS
from backend.services.qdrant import search_legal_knowledge, get_user_memory

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

TOPIC_LABELS = {
    "theft": "theft",
    "theft_complaint": "theft",
    "fir_process": "FIR process",
    "domestic_violence": "domestic violence",
    "harassment": "harassment",
    "wage_theft": "unpaid wages",
    "land_dispute": "land dispute",
    "cyber_crime": "cyber crime",
    "consumer_rights": "consumer rights",
    "legal_aid": "free legal aid",
    "rti": "RTI",
    "child_rights": "child rights",
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
    "legal_aid": [
        "free legal aid DLSA NALSA 15100 India",
    ],
    "rti": [
        "RTI application fee 30 days appeal India",
    ],
    "child_rights": [
        "child helpline 1098 POCSO child labour complaint India",
    ],
}

INTENT_PATTERNS: Dict[str, str] = {
    "theft_complaint": r"chori|theft|stolen|चोरी|phone|फ़ोन|snatch|rob|loot|लूट",
    "domestic_violence": r"violen|hinsa|हिंसा|मार|domestic|abuse|beat|पीट|dv|498",
    "harassment": r"harass|posh|उत्पीड़|stalking|eve.?teas|molestation|छेड़",
    "wage_theft": r"wage|vetan|वेतन|salary|pay|भुगतान|mazduri|मज़दूरी|labour|labor",
    "land_dispute": r"land|bhumi|भूमि|ज़मीन|zameen|property|सम्पत्ति|plot|encroach",
    "cyber_crime": r"cyber|hack|online|fraud|धोखा|ऑनलाइन|scam|phishing|sextort",
    "consumer_rights": r"consumer|उपभोक्ता|refund|product|defect|warranty|खराब",
    "rti": r"rti|सूचना|right to info|आरटीआई|information act",
    "fir_process": r"fir|एफ़आईआर|first information|zero fir|police station|थाना",
    "legal_aid": r"free legal|legal aid|nalsa|नालसा|dlsa|free lawyer|15100",
    "child_rights": r"child|बच्च|pocso|juvenile|1098|minor",
    "emergency": r"emergency|help me|bachao|बचाओ|danger|khatra|खतरा|jaan|kill|मार",
}

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
        detected_lang = intent_data.get("language", language_code)
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
            }

        legal_results = _search_legal_knowledge_with_fallback(user_message, intent, top_k=6)
        memories = get_user_memory(user_id, top_k=2)

        strong_results = [r for r in legal_results if r["score"] >= 0.25]
        intent_results = _filter_results_for_intent(legal_results, intent)

        if GEMINI_API_KEY:
            # Use Gemini LLM to synthesize a tailored response based on RAG context
            context_str = "\n".join([f"[{r['category'].title()}] {r['content']}" for r in legal_results if r['score'] > 0.2])
            reply = _generate_with_gemini(user_message, context_str, detected_lang, conversation)
            if not reply:
                # Fallback if Gemini fails
                if strong_results:
                    reply = _build_grounded_response(user_message, strong_results, intent, detected_lang)
                elif intent_results:
                    reply = _build_grounded_response(user_message, intent_results, intent, detected_lang)
                else:
                    reply = _intent_or_generic_response(user_message, intent, detected_lang)
        else:
            if strong_results:
                reply = _build_grounded_response(user_message, strong_results, intent, detected_lang)
            elif intent_results:
                reply = _build_grounded_response(user_message, intent_results, intent, detected_lang)
            else:
                reply = _intent_or_generic_response(user_message, intent, detected_lang)

        if memories:
            memory_note = _format_memory_note(memories, detected_lang)
            reply = memory_note + "\n\n" + reply

        reply += "\n\n" + _disclaimer(detected_lang)

        store_turn(user_id, user_message, reply, intent)

        return {
            "response": reply,
            "intent": intent,
            "language": detected_lang,
            "follow_up": True,
            "urgency": False,
        }
    except Exception as e:
        logger.error(f"Error generating response for user {user_id}: {str(e)}", exc_info=True)
        return {
            "response": "I apologize, but I'm having trouble processing your request right now. Please try again or contact emergency services if this is urgent.",
            "intent": "error",
            "language": language_code,
            "follow_up": False,
            "urgency": False,
        }


def _generate_with_gemini(user_message: str, context: str, lang: str, conversation: list) -> str:
    """Make REST API call to Gemini to generate natural conversational text using context"""
    language_map = {"hi": "Hindi", "en": "English", "ta": "Tamil", "bn": "Bengali", "mr": "Marathi", "te": "Telugu"}
    lang_name = language_map.get(lang, "English")
    
    system_prompt = (
        f"You are NyayaVoice, a helpful and empathetic legal aid assistant in India. "
        f"Always answer clearly and directly in {lang_name}. Use simple, jargon-free everyday language. "
        f"Use the following 'Legal Context' found from our database to inform your answer. "
        f"Answer the user's exact question first. Do not give a generic category overview when the question is specific. "
        f"If the context is incomplete, say what is known, what is uncertain, and ask one short follow-up question. "
        f"If the context doesn't contain the exact answer, use your general knowledge of Indian Law, "
        f"but advise the user to consult a lawyer. Do not hallucinate section numbers unless certain.\n"
    )
    
    prompt = f"System: {system_prompt}\n\nLegal Context:\n{context}\n\n"
    
    # Add recent conversation history for context
    for msg in conversation[-4:]:
        role = "User" if msg.get("role") == "user" else "NyayaVoice"
        prompt += f"{role}: {msg.get('text')}\n"
        
    prompt += f"User: {user_message}\nNyayaVoice:"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4}
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
        content = r["content"]
        category = r["category"].replace("_", " ").title()
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
    primary_topic = TOPIC_LABELS.get(intent, TOPIC_LABELS.get(top_results[0]["category"], "legal issue"))

    if lang == "hi":
        intro = f"आपके सवाल के हिसाब से, {primary_topic} के लिए यह सबसे काम की जानकारी है:"
        next_steps_label = "अगले कदम:"
        follow_up = "अगर आप चाहें, तो मैं इसी विषय पर एक छोटा ड्राफ्ट या अगले कदम भी बता सकता हूँ।"
    else:
        intro = f"Based on your question, here is the most relevant information about {primary_topic}:"
        next_steps_label = "Next steps:"
        follow_up = "If you want, I can also turn this into a short step-by-step plan or draft."

    key_points = _extract_key_points(top_results)
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
        "domestic_violence": {"domestic_violence"},
        "harassment": {"harassment", "cyber_crime"},
        "wage_theft": {"wage_theft"},
        "land_dispute": {"land_dispute"},
        "cyber_crime": {"cyber_crime"},
        "consumer_rights": {"consumer_rights"},
        "legal_aid": {"legal_aid"},
        "rti": {"rti"},
        "child_rights": {"child_rights"},
    }
    allowed = intent_categories.get(intent, set())
    filtered = [r for r in results if r.get("category") in allowed]
    return filtered[:3]


def _extract_key_points(results: list) -> list:
    seen = set()
    points = []
    for result in results:
        sentences = re.split(r"(?<=[.!?])\s+", result["content"].strip())
        for sentence in sentences:
            cleaned = sentence.strip().replace("\n", " ")
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
    if ("where" in lower and "fir" in lower) or ("report" in lower and "fir" in lower):
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
    if intent == "cyber_crime":
        return _cyber_guidance(lang)
    if intent == "consumer_rights":
        return _consumer_guidance(lang)
    if intent == "legal_aid":
        return _legal_aid_guidance(lang)
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


def _cyber_guidance(lang: str) -> str:
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


def _consumer_guidance(lang: str) -> str:
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


def _is_vague_question(user_message: str) -> bool:
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

    if doc_type == "FIR":
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
