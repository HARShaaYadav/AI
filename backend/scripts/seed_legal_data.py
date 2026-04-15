"""
Seed Qdrant with legal knowledge.
Run from the nyayavoice/ directory:
    python -m scripts.seed_legal_data
"""
import sys
import os

# Ensure nyayavoice/ is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.qdrant import ensure_collections, seed_legal_document

LEGAL_DATA = [
    # ── Theft ──────────────────────────────────────────────────────────────
    {
        "content": (
            "If someone steals your belongings, you have the right to file a First Information Report (FIR) "
            "at the nearest police station. This is completely free. The police are legally required to register "
            "your FIR under Section 379 of the Indian Penal Code (IPC). You are entitled to a free copy of the FIR."
        ),
        "category": "theft",
    },
    {
        "content": (
            "To file an FIR for theft, provide: what was stolen, when it happened, where it happened, "
            "and any details about the suspect. You can also file an e-FIR online in many states. "
            "If police refuse to register your FIR, complain to the Superintendent of Police or file "
            "a complaint in court under Section 156(3) CrPC."
        ),
        "category": "theft",
    },
    # ── Domestic Violence ──────────────────────────────────────────────────
    {
        "content": (
            "Under the Protection of Women from Domestic Violence Act 2005, any woman facing physical, "
            "emotional, sexual, or economic abuse by a family member can file a complaint. "
            "Call Women Helpline 181 for immediate help. You can approach a Protection Officer, "
            "file a complaint at the police station, or contact an NGO."
        ),
        "category": "domestic_violence",
    },
    {
        "content": (
            "The court can issue a Protection Order to stop the abuser from contacting the victim. "
            "The victim can also get a Residence Order allowing her to stay in the shared household. "
            "Monetary relief and custody orders for children can also be obtained under the DV Act 2005."
        ),
        "category": "domestic_violence",
    },
    # ── Harassment ─────────────────────────────────────────────────────────
    {
        "content": (
            "Sexual harassment at the workplace is covered under the POSH Act 2013. "
            "Every company with 10 or more employees must have an Internal Complaints Committee (ICC). "
            "You can file a complaint with the ICC within 3 months of the incident. "
            "If no ICC exists, file with the Local Complaints Committee (LCC) at the district level."
        ),
        "category": "harassment",
    },
    {
        "content": (
            "If you face harassment on the street or in public, you can file a complaint under "
            "Section 354 of the IPC (assault or criminal force to outrage modesty). "
            "Call police helpline 100 or women helpline 181. "
            "Cyberstalking and online harassment can be reported at cybercrime.gov.in or call 1930."
        ),
        "category": "harassment",
    },
    # ── Wage Theft / Labour Rights ─────────────────────────────────────────
    {
        "content": (
            "Every worker has the right to receive their full wages on time under the Payment of Wages Act. "
            "If your employer withholds your salary, file a complaint with the Labour Commissioner in your district. "
            "This is free and you do not need a lawyer. Migrant workers have the same rights as local workers."
        ),
        "category": "wage_theft",
    },
    {
        "content": (
            "Under the Minimum Wages Act, every employer must pay at least the minimum wage set by the state government. "
            "If you are paid less, complain to the Labour Department. "
            "Under the Contract Labour Act, contract workers are also entitled to minimum wages and basic facilities. "
            "You can also approach the Labour Court for unpaid wages."
        ),
        "category": "wage_theft",
    },
    # ── Land Disputes ──────────────────────────────────────────────────────
    {
        "content": (
            "If someone illegally occupies your land or property, file a complaint at the local police station "
            "or approach the Revenue Court (Tehsildar). Keep all documents like sale deed, property tax receipts, "
            "and Aadhaar-linked land records as evidence. You can also file a civil suit for possession."
        ),
        "category": "land_dispute",
    },
    # ── FIR Process ────────────────────────────────────────────────────────
    {
        "content": (
            "An FIR (First Information Report) is the first step in reporting a crime. "
            "You have the right to get a free copy of your FIR. "
            "If the police refuse to register your FIR, you can complain to the Superintendent of Police "
            "or file a complaint in court under Section 156(3) CrPC."
        ),
        "category": "fir_process",
    },
    {
        "content": (
            "You can file an FIR at any police station, not just the one in the area where the crime happened. "
            "This is called a Zero FIR. The police must then transfer it to the correct station. "
            "After filing, you will receive an FIR number which you can use to track your case."
        ),
        "category": "fir_process",
    },
    # ── Legal Aid ──────────────────────────────────────────────────────────
    {
        "content": (
            "Free legal aid is available to all citizens who cannot afford a lawyer. "
            "Contact the District Legal Services Authority (DLSA) in your district. "
            "Women, children, SC/ST individuals, persons with disabilities, and people below poverty line "
            "are entitled to free legal aid under the Legal Services Authorities Act 1987."
        ),
        "category": "legal_aid",
    },
    {
        "content": (
            "The National Legal Services Authority (NALSA) provides free legal services. "
            "Call their helpline 15100 for free legal advice. "
            "Lok Adalats provide free and fast dispute resolution — their decisions are final and binding. "
            "You can also get free legal aid from State Legal Services Authorities (SLSA)."
        ),
        "category": "legal_aid",
    },
    # ── Emergency ──────────────────────────────────────────────────────────
    {
        "content": (
            "Emergency helpline numbers in India: "
            "Police: 100 | Fire: 101 | Ambulance: 102 | "
            "Emergency (all services): 112 | Women Helpline: 181 | "
            "Child Helpline: 1098 | Senior Citizen Helpline: 14567 | "
            "Cyber Crime: 1930 | NALSA Legal Aid: 15100 | "
            "Anti-Poison: 1066 | Disaster Management: 1078"
        ),
        "category": "emergency",
    },
    # ── Cyber Crime ────────────────────────────────────────────────────────
    {
        "content": (
            "If you are a victim of online fraud, cyberbullying, identity theft, or sextortion, "
            "report it at cybercrime.gov.in or call 1930. "
            "You can also file an FIR at your local police station under the IT Act 2000. "
            "Preserve all evidence: screenshots, emails, transaction IDs before reporting."
        ),
        "category": "cyber_crime",
    },
    # ── Consumer Rights ────────────────────────────────────────────────────
    {
        "content": (
            "Under the Consumer Protection Act 2019, you have the right to file a complaint against "
            "a seller or service provider for defective goods, poor service, or overcharging. "
            "File online at edaakhil.nic.in or visit the District Consumer Forum. "
            "Claims up to Rs 50 lakh go to District Forum, up to Rs 2 crore to State Commission."
        ),
        "category": "consumer_rights",
    },
    # ── Right to Information ───────────────────────────────────────────────
    {
        "content": (
            "Under the Right to Information Act 2005, every citizen can request information from "
            "any government office. File an RTI application with a fee of Rs 10. "
            "The government must respond within 30 days. "
            "If denied, appeal to the First Appellate Authority and then to the Information Commission."
        ),
        "category": "rti",
    },
    # ── Child Rights ───────────────────────────────────────────────────────
    {
        "content": (
            "Child labour is illegal in India for children below 14 years under the Child Labour Act. "
            "If you see a child being forced to work, call Child Helpline 1098. "
            "Under the POCSO Act 2012, any sexual offence against a child must be reported to police. "
            "Every child has the right to free education up to age 14 under the RTE Act 2009."
        ),
        "category": "child_rights",
    },
]


def main():
    print("Connecting to Qdrant and ensuring collections exist...")
    ensure_collections()

    print(f"\nSeeding {len(LEGAL_DATA)} legal knowledge entries into Qdrant...")
    for i, item in enumerate(LEGAL_DATA, 1):
        seed_legal_document(
            content=item["content"],
            category=item["category"],
            language="en",
        )
        print(f"  [{i:02d}/{len(LEGAL_DATA)}] ✓ {item['category']}")

    print(f"\n✅ Done! {len(LEGAL_DATA)} entries seeded into the legal knowledge base.")


if __name__ == "__main__":
    main()
