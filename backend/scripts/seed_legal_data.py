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
    # ── Constitutional Rights ─────────────────────────────────────────────
    {
        "content": (
            "Article 14 of the Constitution of India guarantees equality before the law and equal protection of the laws. "
            "This means the State must treat people fairly and cannot act arbitrarily."
        ),
        "category": "constitutional_rights",
    },
    {
        "content": (
            "Article 19 of the Constitution protects key freedoms such as speech and expression, peaceful assembly, "
            "association, movement, residence, and profession, subject to reasonable restrictions under law."
        ),
        "category": "constitutional_rights",
    },
    {
        "content": (
            "Article 21 protects life and personal liberty. In simple terms, the government cannot take away your liberty "
            "except through a valid legal process. Courts have treated dignity, fair procedure, and privacy as part of this protection."
        ),
        "category": "constitutional_rights",
    },
    {
        "content": (
            "Article 22 gives important arrest protections. A person who is arrested should be told the grounds of arrest, "
            "has the right to consult a lawyer, and must usually be produced before a magistrate within 24 hours."
        ),
        "category": "constitutional_rights",
    },
    {
        "content": (
            "Article 32 allows a person to approach the Supreme Court to enforce Fundamental Rights. "
            "High Courts can also be approached under Article 226 for many rights-related legal remedies."
        ),
        "category": "constitutional_rights",
    },
    {
        "content": (
            "Article 39A directs the State to provide equal justice and free legal aid so that lack of money does not block access to justice. "
            "This is why legal aid services are available through DLSA, SLSA, and NALSA."
        ),
        "category": "constitutional_rights",
    },
    # ── Criminal Law Basics ───────────────────────────────────────────────
    {
        "content": (
            "India's main criminal law is now the Bharatiya Nyaya Sanhita, 2023, which came into force on 1 July 2024. "
            "Many people still use old IPC terms in everyday speech, so it is helpful to explain both the older IPC name and the current law when needed."
        ),
        "category": "criminal_law_basics",
    },
    {
        "content": (
            "Under the Bharatiya Nyaya Sanhita, theft is covered in section 303, snatching in section 304, extortion in section 308, "
            "and robbery in section 309. In plain language, theft is taking property dishonestly, while robbery involves theft or extortion with immediate violence or fear."
        ),
        "category": "criminal_law_basics",
    },
    {
        "content": (
            "Under the Bharatiya Nyaya Sanhita, wrongful restraint is covered in section 126 and wrongful confinement in section 127. "
            "Wrongful restraint means illegally stopping someone from moving in a direction they can lawfully go. "
            "Wrongful confinement is more serious and means keeping someone trapped within limits."
        ),
        "category": "criminal_law_basics",
    },
    {
        "content": (
            "Under the Bharatiya Nyaya Sanhita, force, criminal force, and assault are covered in sections 128 to 131. "
            "In simple terms, assault usually means creating fear of immediate unlawful force, while criminal force means actually using unlawful force."
        ),
        "category": "criminal_law_basics",
    },
    {
        "content": (
            "The right of private defence is recognised under the Bharatiya Nyaya Sanhita. "
            "A person may defend their body or property against certain unlawful attacks, but the force used should stay within lawful limits and depend on the danger faced."
        ),
        "category": "criminal_law_basics",
    },
    # Property and Rent Issues
    {
        "content": (
            "Property and rent issues commonly include landlord not returning deposit, illegal eviction, rent agreement disputes, builder delay, and property fraud. "
            "In these matters, collect the agreement and payment proof first, then send a legal notice. "
            "Depending on the issue, the matter may go to Civil Court, Rent Tribunal, or Consumer Court in builder cases."
        ),
        "category": "property_rent",
    },
    {
        "content": (
            "Useful documents in property and rent issues include rent agreement, payment receipts, bank statement, chats or emails, and photos or videos. "
            "Written agreements and payment proof are much stronger than verbal arrangements."
        ),
        "category": "property_rent",
    },
    # Family and Personal Issues
    {
        "content": (
            "Family issues commonly include divorce, domestic violence, child custody, and dowry harassment. "
            "If there is abuse or threat, approach the police or relevant authority without delay and preserve evidence. "
            "Depending on the issue, the matter may be filed in Family Court or at the police station."
        ),
        "category": "family_personal",
    },
    {
        "content": (
            "Important documents in family disputes may include marriage certificate, medical reports, chats or recordings, and income proof. "
            "In abuse cases, medical records and written messages can be very important evidence."
        ),
        "category": "family_personal",
    },
    # Employment and Workplace Issues
    {
        "content": (
            "Employment issues commonly include salary not paid, wrongful termination, and workplace harassment. "
            "Start by collecting emails and the offer letter, then raise an internal complaint. "
            "Depending on the issue, the matter may go to the Labour Court or ICC in harassment cases."
        ),
        "category": "workplace_issues",
    },
    {
        "content": (
            "Useful documents in employment disputes include offer letter, salary slips, bank statement, and emails. "
            "Even if there is no formal contract, emails and salary credits can still be important evidence."
        ),
        "category": "workplace_issues",
    },
    # Traffic and Public Issues
    {
        "content": (
            "Traffic issues commonly include accidents, vehicle theft, and insurance claim issues. "
            "Usually, you should gather evidence quickly and contact police where necessary. "
            "Depending on the issue, the matter may go to the Traffic Police or MACT Tribunal."
        ),
        "category": "traffic_public",
    },
    {
        "content": (
            "Important documents in traffic matters include driving license, RC, insurance, and FIR. "
            "Photos, videos, medical reports, and repair bills can also help make the case stronger."
        ),
        "category": "traffic_public",
    },
    # Financial and Banking Issues
    {
        "content": (
            "Financial and banking issues commonly include bank fraud, cheque bounce, and loan harassment. "
            "Inform the bank immediately and preserve proof. Depending on the dispute, you may need the RBI Ombudsman or the police."
        ),
        "category": "financial_banking",
    },
    {
        "content": (
            "Useful documents in financial and banking disputes include bank statement, cheque and memo, and loan documents. "
            "In cheque-bounce matters, the cheque and bank return memo are especially important."
        ),
        "category": "financial_banking",
    },
    # Detailed evidence for existing cyber and consumer categories
    {
        "content": (
            "In cyber and online crime cases such as online fraud, UPI scams, identity theft, hacking, cyber stalking, revenge porn, fake profiles, OTP fraud, phishing, crypto scams, fake e-commerce sites, "
            "and deepfake misuse, preserve screenshots, transaction receipts, bank or UPI statements, phone numbers or IDs used by the scammer, website links, app details, call recordings if available, "
            "device logs, and complaint acknowledgement from the cyber portal. Report quickly because digital evidence can disappear fast."
        ),
        "category": "cyber_crime",
    },
    {
        "content": (
            "In consumer complaints such as defective products, fake products, service deficiency, wrong billing, non-delivery, refund denial, warranty disputes, hidden charges, misleading ads, and subscription traps, "
            "keep the invoice or bill, warranty card, order confirmation email, payment proof, screenshots of complaints to the company, product photos or videos, delivery receipt, and advertisement copy if there was a misleading claim."
        ),
        "category": "consumer_rights",
    },
    # General process and universal evidence
    {
        "content": (
            "For many legal matters, a common step-by-step process is: collect evidence, send a legal notice, file a complaint or FIR where needed, hire a lawyer if necessary, and attend hearings. "
            "Criminal matters usually begin with police or FIR, while civil disputes often go to court or tribunal."
        ),
        "category": "general_legal_query",
    },
    {
        "content": (
            "Strong evidence in many legal cases can include government ID, address proof, written agreements, photographs, videos, audio recordings if lawfully obtained, witness statements, emails, chats, logs, receipts, "
            "bank statements, and official records. Clear written and digital proof often makes a case much stronger."
        ),
        "category": "general_legal_query",
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
