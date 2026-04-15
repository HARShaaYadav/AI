"""
Response engine — works without any external LLM API.
Uses Qdrant semantic search + keyword intent detection + template formatting.
Voice calls go through Vapi (which handles LLM on its own credits).
"""
import re
import logging
from typing import Dict, List, Any, Optional

from backend.config import SUPPORTED_LANGUAGES, EMERGENCY_KEYWORDS
from backend.services.qdrant import search_legal_knowledge, get_user_memory

logger = logging.getLogger(__name__)

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

        legal_results = search_legal_knowledge(user_message, top_k=4)
        memories = get_user_memory(user_id, top_k=2)

        if legal_results and legal_results[0]["score"] > 0.3:
            reply = _format_legal_results(legal_results, detected_lang)
        else:
            reply = _generic_guidance(detected_lang)

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
    except Exception as e:
        return {
            "response": f"An error occurred: {str(e)}",
            "intent": "error",
            "language": language_code,
            "follow_up": False,
            "urgency": False,
        }


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
