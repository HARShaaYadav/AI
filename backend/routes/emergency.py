import logging
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_PHONE_NUMBER,
    VAPI_API_KEY,
    VAPI_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class EmergencyAlertRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    language: str = Field("en")
    message_mode: Literal["sms", "call"] = Field("sms")
    emergency_type: str = Field(default="general")
    custom_message: Optional[str] = Field(default="")
    contacts: List[str] = Field(..., min_length=1, max_length=5)
    latitude: float = Field(...)
    longitude: float = Field(...)

    @field_validator("contacts")
    @classmethod
    def validate_contacts(cls, contacts: List[str]) -> List[str]:
        cleaned: List[str] = []
        for contact in contacts:
            normalized = "".join(ch for ch in str(contact or "") if ch.isdigit() or ch == "+").strip()
            if not normalized:
                continue
            cleaned.append(normalized)
        if not cleaned:
            raise ValueError("At least one valid contact is required")
        return cleaned


class EmergencyAlertResponse(BaseModel):
    ok: bool
    message: str
    delivery_mode: str
    location_label: str
    generated_message: str
    deliveries: List[Dict[str, Any]]
    source: str


async def _reverse_geocode(latitude: float, longitude: float) -> Dict[str, Any]:
    params = {
        "format": "jsonv2",
        "lat": latitude,
        "lon": longitude,
        "zoom": 18,
        "addressdetails": 1,
    }
    headers = {
        "User-Agent": "NyayaVoice/2.0 emergency-alerts",
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(
            "https://nominatim.openstreetmap.org/reverse",
            params=params,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


def _build_location_text(latitude: float, longitude: float, geocode: Optional[Dict[str, Any]]) -> str:
    display_name = (geocode or {}).get("display_name")
    map_link = f"https://www.openstreetmap.org/?mlat={latitude:.6f}&mlon={longitude:.6f}#map=18/{latitude:.6f}/{longitude:.6f}"
    if display_name:
        return f"{display_name}\nMap: {map_link}"
    return f"Lat: {latitude:.6f}, Lon: {longitude:.6f}\nMap: {map_link}"


async def _generate_vapi_message(
    *,
    language: str,
    emergency_type: str,
    custom_message: str,
    location_text: str,
) -> Optional[str]:
    if not VAPI_API_KEY:
        return None

    prompt = (
        "Write a short emergency alert message for a trusted contact. "
        f"Language: {language}. "
        f"Emergency type: {emergency_type}. "
        "Keep it under 70 words, direct, human, and suitable for both SMS and a phone call voice script. "
        "Mention that this message is sent from NyayaVoice, ask the contact to call back immediately, "
        "and include the live location exactly as provided. "
        f"User details: {custom_message or 'No extra details provided.'} "
        f"Live location: {location_text}"
    )

    headers = {
        "Authorization": f"Bearer {VAPI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "input": prompt,
    }

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.post(
            "https://api.vapi.ai/chat/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    output = data.get("output") or []
    for item in output:
        for content_item in item.get("content") or []:
            if content_item.get("type") == "output_text" and content_item.get("text"):
                return str(content_item["text"]).strip()
    return None


def _fallback_alert_message(
    *,
    language: str,
    emergency_type: str,
    custom_message: str,
    location_text: str,
) -> str:
    emergency_label = emergency_type.replace("_", " ").strip() or "emergency"
    if language == "hi":
        detail = f" स्थिति: {custom_message.strip()}" if custom_message and custom_message.strip() else ""
        return (
            f"यह NyayaVoice से आपातकालीन संदेश है। मुझे तुरंत मदद की जरूरत है ({emergency_label})."
            f"{detail} कृपया तुरंत मुझे कॉल करें। मेरी लाइव लोकेशन:\n{location_text}"
        )
    detail = f" Details: {custom_message.strip()}" if custom_message and custom_message.strip() else ""
    return (
        f"This is an emergency alert from NyayaVoice. I need immediate help ({emergency_label})."
        f"{detail} Please call me back right away. My live location:\n{location_text}"
    )


async def _send_sms_via_twilio(to_number: str, body: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "To": to_number,
                "From": TWILIO_PHONE_NUMBER,
                "Body": body,
            },
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Twilio SMS failed for {to_number}: {response.text}")
    data = response.json()
    return {
        "to": to_number,
        "sid": data.get("sid"),
        "status": data.get("status"),
        "type": "sms",
    }


def _build_vapi_emergency_assistant(*, body: str, language: str) -> Dict[str, Any]:
    language_name = "Hindi" if language == "hi" else "English"
    return {
        "firstMessage": body,
        "firstMessageMode": "assistant-speaks-first",
        "backgroundSound": "off",
        "maxDurationSeconds": 40,
        "endCallMessage": None,
        "hooks": [
            {
                "on": "call.timeElapsed",
                "options": {"seconds": 18},
                "do": [
                    {
                        "type": "tool",
                        "tool": {"type": "endCall"},
                    }
                ],
                "name": "auto_end_emergency_call",
            }
        ],
        "model": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an automated emergency contact notifier for NyayaVoice. "
                        f"Speak in {language_name}. "
                        "Start by reading the emergency alert exactly as provided in the first message. "
                        "If the recipient asks a question, briefly explain that this is an automated emergency alert, "
                        "repeat the live location if needed, and ask them to contact the user immediately. "
                        "Keep every reply under 30 words."
                    ),
                }
            ],
        },
        "voice": {
            "provider": "azure",
            "voiceId": "multilingual-auto",
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "multi",
        },
    }


async def _make_voice_call_via_vapi(to_number: str, body: str, language: str) -> Dict[str, Any]:
    if not VAPI_API_KEY:
        raise HTTPException(status_code=500, detail="Vapi is not configured. Set VAPI_API_KEY.")
    if not VAPI_PHONE_NUMBER_ID:
        raise HTTPException(
            status_code=500,
            detail="Vapi outbound calling is not configured. Set VAPI_PHONE_NUMBER_ID from your Vapi phone number.",
        )

    payload = {
        "assistant": _build_vapi_emergency_assistant(body=body, language=language),
        "phoneNumberId": VAPI_PHONE_NUMBER_ID,
        "customer": {
            "number": to_number,
        },
        "metadata": {
            "purpose": "emergency_contact_alert",
            "language": language,
        },
    }

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        response = await client.post(
            "https://api.vapi.ai/call",
            headers={
                "Authorization": f"Bearer {VAPI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Vapi call failed for {to_number}: {response.text}")
    data = response.json()
    return {
        "to": to_number,
        "sid": data.get("id"),
        "status": data.get("status"),
        "type": "call",
        "provider": "vapi",
    }


@router.post("/emergency-alert", response_model=EmergencyAlertResponse)
async def send_emergency_alert(req: EmergencyAlertRequest) -> EmergencyAlertResponse:
    if req.message_mode == "sms" and not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER):
        raise HTTPException(
            status_code=500,
            detail="Twilio is not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER.",
        )

    geocode: Optional[Dict[str, Any]] = None
    location_label = f"{req.latitude:.6f}, {req.longitude:.6f}"
    try:
        geocode = await _reverse_geocode(req.latitude, req.longitude)
        location_label = geocode.get("display_name") or location_label
    except Exception as err:
        logger.warning("Emergency reverse geocoding failed: %s", err)

    location_text = _build_location_text(req.latitude, req.longitude, geocode)

    generated_message = None
    source = "fallback_template"
    try:
        generated_message = await _generate_vapi_message(
            language=req.language,
            emergency_type=req.emergency_type,
            custom_message=req.custom_message or "",
            location_text=location_text,
        )
        if generated_message:
            source = "vapi_chat_responses"
    except Exception as err:
        logger.warning("Vapi emergency message generation failed: %s", err)

    final_message = generated_message or _fallback_alert_message(
        language=req.language,
        emergency_type=req.emergency_type,
        custom_message=req.custom_message or "",
        location_text=location_text,
    )

    deliveries: List[Dict[str, Any]] = []
    for contact in req.contacts:
        if req.message_mode == "call":
            deliveries.append(await _make_voice_call_via_vapi(contact, final_message, req.language))
        else:
            deliveries.append(await _send_sms_via_twilio(contact, final_message))

    return EmergencyAlertResponse(
        ok=True,
        message="Emergency alert sent successfully.",
        delivery_mode=req.message_mode,
        location_label=location_label,
        generated_message=final_message,
        deliveries=deliveries,
        source=source,
    )
