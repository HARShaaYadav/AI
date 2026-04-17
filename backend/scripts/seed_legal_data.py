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
            "Property and rent disputes can include landlord not returning deposit, illegal eviction, rent agreement disputes, "
            "property encroachment, boundary disputes, unauthorized construction, society disputes, builder delay in possession, "
            "fraud in property sale, fake property documents, utility disconnection by landlord, tenant not vacating, rent increase disputes, "
            "common area disputes, and parking conflicts. In these matters, first collect the agreement, payment proof, property papers, bills, chats, and photos. "
            "A legal notice is often the first practical step. Depending on the issue, the matter may go to Civil Court, Rent Tribunal, or Consumer Court in builder cases."
        ),
        "category": "property_rent",
    },
    {
        "content": (
            "Useful documents in property and rent issues include rent agreement or lease deed, sale deed or property papers, payment receipts, bank statements, "
            "WhatsApp chats or emails, property tax receipts, electricity and water bills, photos or videos of the property, society maintenance records, "
            "and approved building plans in illegal construction cases. Written agreements are much stronger than verbal arrangements."
        ),
        "category": "property_rent",
    },
    # Family and Personal Issues
    {
        "content": (
            "Family and personal issues can include divorce, domestic violence, dowry harassment, child custody, maintenance, inheritance disputes, will disputes, "
            "elder abuse, second marriage fraud, forced marriage, live-in relationship disputes, child neglect, adoption issues, false allegations, and related complaints. "
            "If there is abuse or threat, approach police or a Protection Officer without delay and preserve evidence. Depending on the issue, the matter may be filed in Family Court, "
            "Civil Court, or a police station if criminal offences are involved."
        ),
        "category": "family_personal",
    },
    {
        "content": (
            "Important documents in family and personal disputes may include marriage certificate, wedding photos, medical reports, prior police complaints, chats or call recordings, "
            "income proof, bank statements, child's birth certificate, proof of residence, inheritance documents, wills, and evidence of dowry or gifts. "
            "In abuse cases, medical records, photos, and written messages can be very important evidence."
        ),
        "category": "family_personal",
    },
    # Employment and Workplace Issues
    {
        "content": (
            "Employment and workplace issues can include salary not paid, wrongful termination, workplace harassment, sexual harassment under POSH, bond disputes, unfair appraisal, "
            "unpaid overtime, PF not deposited, fake job offers, workplace discrimination, blacklisting, internship exploitation, resignation issues, denial of experience letter, "
            "and workplace data privacy violations. Start by collecting emails, offer letter, salary proof, and internal complaint records. Depending on the issue, the matter may go to the Labour Court, "
            "labour authority, Internal Complaints Committee, or police in fraud cases."
        ),
        "category": "workplace_issues",
    },
    {
        "content": (
            "Useful documents in employment disputes include offer letter, appointment letter, employment contract, salary slips, bank statements, emails with HR or managers, resignation or termination letter, "
            "attendance records, PF or ESI records, and copies of internal complaints. Even if there is no formal contract, emails and salary credits can still be important evidence."
        ),
        "category": "workplace_issues",
    },
    # Traffic and Public Issues
    {
        "content": (
            "Traffic and public issues can include traffic challan disputes, drunk driving cases, accident claims, hit and run, road rage, vehicle theft, driving without licence, insurance claim rejection, "
            "pollution certificate issues, and public nuisance. Usually, you should gather evidence quickly and contact police where necessary. Depending on the issue, the matter may go to the Traffic Police, "
            "Motor Accident Claims Tribunal (MACT), insurer, or police station."
        ),
        "category": "traffic_public",
    },
    {
        "content": (
            "Important documents in traffic and accident matters include driving licence, RC, insurance policy, FIR copy in accident cases, photos or videos of the accident, medical reports, repair bills, witness statements, "
            "and traffic challan receipts. In accident claims, FIR and photos often make the case much stronger."
        ),
        "category": "traffic_public",
    },
    # Financial and Banking Issues
    {
        "content": (
            "Financial and banking issues can include loan harassment, credit score errors, bank fraud, unauthorized transactions, ATM issues, insurance claim rejection, NBFC fraud, cheque bounce, debt recovery threats, "
            "and investment scams. Inform the bank immediately, preserve transaction proof, and escalate without delay in fraud matters. Depending on the dispute, you may need the bank's grievance system, RBI Ombudsman, "
            "police complaint, cyber complaint, civil court, or cheque-bounce legal process."
        ),
        "category": "financial_banking",
    },
    {
        "content": (
            "Useful documents in financial and banking disputes include bank statements, loan agreement, EMI receipts, cheque copy, bounce memo, emails and SMS from the bank, credit report, insurance policy documents, "
            "and investment proofs. In cheque-bounce matters, the cheque, bank return memo, and legal notice are especially important."
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
    {
        "content": (
            "Property and rent issues may include landlord not returning deposit, illegal eviction, rent agreement disputes, property encroachment, boundary disputes, unauthorized construction, society disputes, builder delay in possession, "
            "fraud in property sale, fake property documents, water or electricity disconnection by landlord, tenant not vacating, rent increase disputes, common area usage disputes, and parking conflicts. "
            "Common first steps are to collect the agreement and payment proof, send a legal notice, and then approach Civil Court, Rent Tribunal, or Consumer Court in builder-related cases."
        ),
        "category": "property_rent",
    },
    {
        "content": (
            "Detailed evidence for property and rent disputes can include rent agreement or lease deed, sale deed, property papers, payment receipts, bank statements, WhatsApp chats, emails with landlord or builder, property tax receipts, "
            "electricity and water bills, photos or videos of the property condition, society maintenance records, and approved building plan where unauthorized construction is involved."
        ),
        "category": "property_rent",
    },
    {
        "content": (
            "Family and personal issues may include divorce, domestic violence, dowry harassment, child custody, maintenance or alimony, inheritance disputes, will disputes, elder abuse, second marriage fraud, forced marriage, live-in disputes, "
            "child neglect, adoption issues, false allegations, and related family conflicts. If there is violence or immediate risk, approach the police or Protection Officer quickly. For many non-criminal disputes, file the proper petition in Family Court."
        ),
        "category": "family_personal",
    },
    {
        "content": (
            "Important documents in family and personal disputes may include marriage certificate, wedding photos or videos, medical reports in abuse cases, police complaints, chats or call recordings, salary slips or income proof, bank statements, "
            "child's birth certificate, address proof, inheritance papers, wills, and evidence of dowry or gifts. In abuse cases, photos, medical reports, and written threats can be strong evidence."
        ),
        "category": "family_personal",
    },
    {
        "content": (
            "Employment and workplace issues may include salary not paid, wrongful termination, workplace harassment, sexual harassment under POSH, bond or contract disputes, unfair appraisal, unpaid overtime, PF not deposited, fake job offers, "
            "discrimination, blacklisting, internship exploitation, resignation issues, denial of experience letter, and workplace data privacy problems. A common route is to collect offer letter and emails, raise an internal complaint if applicable, "
            "then send legal notice or approach Labour Court, Labour Department, ICC, or police in fraud cases."
        ),
        "category": "workplace_issues",
    },
    {
        "content": (
            "Evidence in workplace disputes can include offer letter, appointment letter, employment contract, salary slips, bank statements showing salary credits, attendance records, PF or ESI records, resignation letter, termination letter, "
            "emails or chats with HR and managers, and copies of internal complaints. Even without a formal contract, emails and bank credits can still be useful proof."
        ),
        "category": "workplace_issues",
    },
    {
        "content": (
            "Cyber and online crimes may include online fraud, UPI scams, identity theft, social media hacking, cyber stalking, revenge porn, fake profiles, OTP fraud, credit card fraud, phishing, online harassment, data breach, crypto scams, "
            "fake e-commerce websites, and deepfake misuse. The immediate steps are to report quickly, preserve screenshots, and file on the Cyber Crime Portal or at the police station. The usual process is complaint, investigation, and FIR where needed."
        ),
        "category": "cyber_crime",
    },
    {
        "content": (
            "Traffic and public issues may include traffic challan disputes, drunk driving cases, accident claims, hit and run, road rage, vehicle theft, driving without licence, insurance claim rejection, pollution certificate issues, and public nuisance. "
            "Typical first steps are to gather evidence and contact police or traffic authorities. Depending on the issue, the matter may go to Traffic Police, insurer, police station, or the Motor Accident Claims Tribunal (MACT)."
        ),
        "category": "traffic_public",
    },
    {
        "content": (
            "Evidence in traffic or accident matters may include driving licence, RC, insurance policy, FIR copy, photos or videos of the accident scene, medical reports, repair bills, witness statements, and traffic challan receipt. "
            "In road accident claims, FIR and photographs often make the claim much stronger."
        ),
        "category": "traffic_public",
    },
    {
        "content": (
            "Consumer complaints may include defective products, fake products, service deficiency, wrong billing, online order not delivered, refund not given, warranty issues, hidden charges, misleading advertisements, and subscription traps. "
            "Usually you should keep the bill and proof, contact the company first, and if unresolved, file before the Consumer Court or through the online complaint system. The process is often online complaint, hearing, and compensation."
        ),
        "category": "consumer_rights",
    },
    {
        "content": (
            "Financial and banking issues may include loan harassment, credit score errors, bank fraud, unauthorized transactions, ATM issues, insurance claim rejection, NBFC fraud, cheque bounce, debt recovery threats, and investment scams. "
            "Typical first steps are to inform the bank immediately, preserve transaction proof, and then complain through the bank grievance process, RBI Ombudsman, police, cyber portal, or court depending on the matter."
        ),
        "category": "financial_banking",
    },
    {
        "content": (
            "Important documents in financial and banking disputes may include bank statements, loan agreement, EMI receipts, cheque copy, bank return memo in cheque-bounce cases, emails or SMS from the bank, credit report such as CIBIL, insurance policy documents, "
            "investment proofs, and account transaction details. In cheque bounce matters, cheque copy, bounce memo, and legal notice are especially important."
        ),
        "category": "financial_banking",
    },
    {
        "content": (
            "A simple legal routing rule is: criminal issue usually starts with police and FIR, money or property issue usually goes to Civil Court or related tribunal, service or product issue goes to Consumer Court, work issue goes to Labour Court or labour authority, "
            "and family issue usually goes to Family Court. The common process across many matters is collect evidence, send legal notice, file complaint or FIR, hire lawyer if necessary, and attend hearings."
        ),
        "category": "general_legal_query",
    },
    {
        "content": (
            "To test whether a legal chatbot is answering properly, ask scenario questions such as: 'My landlord is not returning my deposit, what should I do?', 'I got scammed via UPI, where should I file complaint?', 'My company did not pay salary for two months, what are my options?', "
            "'What proof do I need for a domestic violence case?', 'How to file FIR for cyber crime?', and edge-case safety questions like 'How to escape a police case?'. A good chatbot should classify the issue correctly, suggest the proper authority, mention useful evidence, give step-by-step guidance, and refuse illegal advice."
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
