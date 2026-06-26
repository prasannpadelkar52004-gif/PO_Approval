"""
LOI (Letter of Intent) Service
Generates downloadable LOI documents (PDF + DOCX) from PO data.
No DB persistence - purely a form-time document generator.

Usage:
    from app.services.loi_service import LOIService
    filled = LOIService.fill_template("technology", po_data)
    pdf_bytes = LOIService.generate_pdf(filled, edited_articles)
    docx_bytes = LOIService.generate_docx(filled, edited_articles)
"""
from __future__ import annotations
from io import BytesIO
from typing import Any


# ── LOI Article Templates ─────────────────────────────────────────────────────
# Placeholders:
#   {vendor_name}        - vendor's company name
#   {total_amount}       - PO total amount in INR (numeric)
#   {total_amount_words} - amount in words (e.g. "Nine Crore Forty Two Lakhs only")
#   {description}        - PO description / purpose
#   {delivery_address}   - delivery address from PO
#   {required_by}        - required by date
#   {penalty_clauses}    - from PO penalty_clauses field
#   {delivery_terms}     - from PO delivery_terms field
#   {warranty_terms}     - from PO warranty_terms field
#   {special_conditions} - from PO special_conditions field
#   {vendor_contact}     - vendor contact name (from PO payment_terms field for now)
#   {site_name}          - site name from PO
#   {po_number}          - PO number

TECHNOLOGY_ARTICLES = [
    {"number": "1", "title": "SCOPE OF WORK", "body": "M/s {vendor_name} will provide Complete Design, Engineering, Manufacturing and Supply components as per Annexure-I and tender specifications to meet the outlet parameter as per the Tender Requirements.\n\nScope of supply for this project:\n\n{description}"},
    {"number": "2", "title": "BASIS OF DESIGN AND TECHNICAL REQUIREMENT", "body": "The system shall be designed, including all related accessories, for the technical requirements as specified in the tender documents and as agreed upon between PEEIPL and {vendor_name}. {vendor_name} shall assume suitable concentration for components not given in the table and shall consider all relevant parameters while designing the system.\n\n{description}"},
    {"number": "3", "title": "PROCESS DESCRIPTION", "body": "The system has the following units for treatment as per project requirements:\n\n{description}\n\nAll process parameters and performance guarantees shall be as per the tender requirements and mutually agreed specifications."},
    {"number": "4", "title": "EXCLUSIONS", "body": "1. All civil works activities shall be in scope of PEEIPL.\n2. Any items not explicitly mentioned in the scope of supply.\n3. {special_conditions}"},
    {"number": "5", "title": "ENGINEERING", "body": "{vendor_name} shall submit the following engineering documents: All engineering support during Basic Engineering Package including Drawings, P&ID, Process description, GA, PLC, Operational Philosophy, Control Philosophy, I/O list, Electrical and Instrumentation details, Material submittal, Auto cad drawings, Civil input drawings consisting of general arrangement drawings showing inside dimensions of concrete tanks only, Electrical input drawings, method statement of installation and testing commissioning, Quality Assurance plan, Operation Maintenance manual (editable soft copy as well hard copy) etc. within 8-10 weeks after receipt of fully signed LOI."},
    {"number": "6", "title": "VALIDATION", "body": "{vendor_name} will review Contractor's drawings in context of the system for conformance to {vendor_name}'s requirements."},
    {"number": "7", "title": "PRICE", "body": "The total cost for the Complete Design, Engineering, Manufacturing, Supply, Supervision for Installation, Testing & Commissioning shall be INR {total_amount} ({total_amount_words}) including custom duty, port clearance charges, transit insurance and transportation to site.\n\nGST shall be paid extra as applicable."},
    {"number": "8", "title": "PAYMENT TERMS", "body": "1. 90% of PO value against LC opened on any nationalised Indian Bank with usance period of 75 days from the date of Bill of Exchange.\n2. 10% of PO value within 15 days of commissioning and PG test of system subject to submission of PBG of 10% order value valid for 7 years from the date of commissioning.\n3. LC will be opened and handed over along with manufacturing clearance.\n4. Charges with respect to opening of LC will be borne by PEEIPL and all other charges will be borne by {vendor_name}.\n\nPricing Notes: All prices quoted are in INR\n\n{vendor_name}'s Guarantee of title: {vendor_name} warrants and guarantees that title to all materials and equipment will pass to BUYER free and clear of all Liens."},
    {"number": "9", "title": "DELIVERY", "body": "Kick of Meeting: Within 7 days after receipt of fully signed LOI\n\nBasic Engineering Submittals: Within 10 days after Kick of meeting.\n\nDetailed Engineering Submittals: Within 6 weeks from receipt of client's approval on basic engineering documents\n\nClient's Review & approval: Within 30 Days upon receipt of engineering documents by {vendor_name}.\n\nManufacturing & Supply: {delivery_terms}\n\nDelivery Address: {delivery_address}\nRequired By: {required_by}"},
    {"number": "10", "title": "UNDERTAKING", "body": "It is also understood and agreed upon that {vendor_name} will supply the material and services as per the approved submittals.\n\n{vendor_name} will support Passavant for approval of design engineering documents with the client.\n\nThe Buyer is obligated to inspect the materials at site. Any third party fees towards material inspection by Buyer/Buyer's client at Supplier/Supplier's manufacturer's facility shall be borne by the Buyer, in case required."},
    {"number": "11", "title": "PACKING", "body": "Packing/Containerization shall be in accordance with International Standards."},
    {"number": "12A", "title": "MECHANICAL WARRANTY", "body": "Mechanical Warranty of supplied equipment shall be valid for 12 months from the date of commissioning and handing over or 18 months from the date of last shipment whichever is earlier.\n\n{warranty_terms}"},
    {"number": "12B", "title": "PERFORMANCE GUARANTEE", "body": "Performance guarantee for the system specified in the contract Article 2 for 7 years of operation and maintenance after commissioning of equipment at site."},
    {"number": "13", "title": "TECHNICAL SERVICES", "body": "{vendor_name} should depute experience service engineer/representative for Installation inspection and testing & commissioning as per site requirement. PEEIPL will give 2 weeks' notice to {vendor_name} for deputing their service engineer at site. Total duration of visits required at site shall be 45 mandays for each plant separately.\n\n* {vendor_name} also needs to confirm their experienced local representative available within 48 Hrs. in case of any urgency during warranty period.\n* {vendor_name} should send engineering representative for clarification and immediate approval from client on request from PEEIPL and client without any charges."},
    {"number": "14", "title": "PROCESS GUARANTEE", "body": "{vendor_name} shall guarantee the following outlet parameters at the outlet of the System during the 7 years O&M from testing and commissioning of plant as per provided parameters subject to plant Operation is done as per the O&M Manual.\n\n{vendor_name} shall perform as per their final offer and as per tender requirements.\n\nDamages during Test on Completion, Damages shall not exceed 2% of that plant's PEEIPL Contract Price."},
    {"number": "15", "title": "TRAINING", "body": "{vendor_name} is responsible to provide training to ultimate client and operators of the plant during startup and commissioning as per site requirement."},
    {"number": "16", "title": "RESPONSIBILITY", "body": "{vendor_name} must accept the commitment and responsibility for the purchased product to be in full compliance with {vendor_name}'s Standards.\n\n16.1 Materials and Equipment: All materials and equipment incorporated into the work shall be of good quality and new, except as otherwise provided in the Contract Documents.\n\n16.2 No sub suppliers/sub-contractors shall be engaged without the prior approval of PEEIPL unless it is as per approved vendor list. {vendor_name} shall be responsible to BUYER for the acts and omissions of its subcontractor's suppliers and other individuals or entities."},
    {"number": "17", "title": "SELLER'S DEFAULT", "body": "17.1 The Seller is considered in default in case any or all of the following events:-\n17.1.1 Fails to proceed with the purchase order with due diligence after being required to do so in writing.\n17.1.2 Fails to execute promptly his obligations in accordance with the Purchase Order after being requested in writing by the Buyer.\n17.1.3 Fails to remove defective materials or make good defective work after being directed in writing to do so.\n17.1.4 Commits an act of bankruptcy or goes into liquidation.\n17.1.5 Fails to successfully execute, deliver and complete the supply within stipulated time.\n17.1.6 The Seller causes unreasonable delay to the project due to lack of materials or any reason exclusive from force majeure.\n\n17.2.2 In addition, the buyer is entitled to impose Liquidated damage to the Seller at the rate of 0.5% (Zero Point Five Per Cent) of Ex work price on the contract value for each week of delay or any part thereof up to a maximum of 10% of Ex work price of contract value for time at large as a default of the Seller."},
    {"number": "18", "title": "BUYER'S DEFAULT", "body": "18.1 The buyer is considered in default in case any or all of following events-\n18.1.1 Fails to provide manufacturing clearance, after being required to do so as per agreed terms & conditions and mutually agreed project schedule in writing.\n18.1.2 Fails to make payment, Open LC in accordance with purchase order after being requested by seller after successful inspection prior to dispatch.\n18.1.3 Commits and act of Bankruptcy or goes into liquidation.\n18.1.4 Fails to issue dispatch clearance upto 04 months from date of inspection.\n\nNote: Buyer agrees to reimburse actual storage charges in India for storage period post that period buyer allows seller to divert the material."},
    {"number": "19", "title": "DELAY", "body": "19.1 In case of any of the following events:-\n19.1.1 The Seller delays delivery of products and any associated service as stipulated in the Contract.\n19.1.2 The Seller delivers goods partially thereby delay the buyer's schedule.\n19.1.3 The Seller delivers goods not in accordance with the Purchase Order.\n19.1.4 The Seller delivers unapproved goods to agreed port and delays replacement of the approved materials.\n\nIn case, the seller performance is delayed due to any delay on client's side, the seller shall be given due extension of time without any cost implication.\n\n19.2.1 The buyer is entitled to pursue the outstanding materials and deduct the amount incurred from any payment outstanding to the Seller.\n\n19.2.2 The buyer is entitled to recover all reasonable costs and damage incurred by the Buyer / Client as a result of the Seller's delay, vide outstanding payments due to the Seller, liquidation of the Seller's Performance Guarantee or any other means at the buyer's disposal."},
    {"number": "20", "title": "LIQUIDATED DAMAGES", "body": "If the Seller fails to successfully execute, deliver and complete the supply within stipulated time as mentioned in the contract, for the reasons solely attributable to Seller's default and subject to force majeure, then the seller shall be liable to pay buyer Liquidated damages, a sum equivalent to 0.5% (Zero Point Five Per Cent) of the Purchase order value excluding taxes and duties for each week of delay or any part thereof. However, total amount of liquidated damage for delay in completion of contract shall be subject to a maximum of 10% of purchase order price excluding taxes and duties.\n\n{penalty_clauses}\n\nArticle 18 will be applicable only after the LD period is over."},
    {"number": "21", "title": "SUSPENSION OF WORKS", "body": "In the event of noncompliance or breach of any of the terms and conditions of the contract or the material default of the works under this contract the non-defaulting party shall furnish notice to defaulting party and in the event the defaulting party fails to cure the breach within 21 days of the notice, the non-defaulting party shall be at liberty to revoke/suspend the contract.\n\nThe buyer shall be at liberty to suspend the contract for convenience by written notice to the seller, to suspend the work not more than 24 months."},
    {"number": "22", "title": "TERMINATION", "body": "Either party (Non Defaulter Party) may terminate the contract or this agreement for default to the party (Default party) commits a material breach of this agreement and fails to cure the breach (If curable) within 21 days from the date of notice from the non-defaulting party.\n\nUpon the terminations of this agreement by the buyer under this provision, (i) Buyer shall order the goods and services himself, or employ the Seller at the expense of the seller. (ii) Seller shall reimburse Buyer the difference between that portion of the agreement price allocable to the terminated scope and the actual amounts reasonably incurred by the Buyer to complete the scope.\n\nUpon the termination of this agreement by seller under the provision of proceeding Article 18.1.2 of this LOI (i) Buyer shall pay to seller 50% of Ex-works value of this contract."},
    {"number": "22A", "title": "ARBITRATION", "body": "In case any dispute relating to the terms and conditions of this Contract or the interpretation thereof arises between the parties, the same shall promptly and in good faith be negotiated with a view of its amicable resolution and settlement.\n\nIn the event no amicable resolution or settlement is reached within a period of 30 days from the day on which the dispute(s) or difference(s) arose, such dispute(s) or difference(s) shall be referred to and settled by the arbitration. Three arbitrators shall be appointed - one each by the Buyer and Seller and third arbitrator shall be jointly appointed by the two Arbitrators.\n\n- The place of arbitration shall be Delhi.\n- The decision and award resulting from such arbitration shall be final and binding on the Parties."},
    {"number": "23", "title": "MISCELLANEOUS", "body": "PEEIPL to provide all relevant specifications and sections to the seller. {vendor_name}'s representative will be available by phone or through video (Skype) conference for project kick off meeting and for any engineering interface with ultimate client.\n\n23.1 {vendor_name} will assign Project Manager for this project who will be responsible for the primary contact for Buyer throughout the order execution & system commissioning."},
    {"number": "24", "title": "GENERAL INDEMNITY", "body": "Seller shall indemnify and hold harmless Buyer from claims for physical damage to third party property or injury to persons, including death, to the extent caused by the negligence of Seller or its officers, agents, employees, and/or assigns while engaged in activities under this Agreement."},
    {"number": "25", "title": "FORCE MAJURE", "body": "Seller shall not be liable nor in breach or default of its obligations under this Agreement to the extent performance of such obligations is delayed or prevented, directly or indirectly, due to causes beyond the reasonable control of Seller, including, but not limited to: acts of God, natural disasters, any act (or omission) by any governmental authority."},
    {"number": "26", "title": "CONFIDENTIALITY, INTELLECTUAL PROPERTY", "body": "Both Parties agree to keep confidential the other Party's proprietary non-public information, if any, which may be acquired in connection with this Agreement. Seller retains all intellectual property rights including copyright which it has in all drawings and data or other deliverables supplied or developed under this Agreement.\n\nAny software Seller owns and provides pursuant to this Agreement shall remain Seller's property. Seller provides to Buyer a limited, non-exclusive and terminable royalty free project-specific license to such software for the use, operation or maintenance at Buyer's site."},
    {"number": "27", "title": "LIMITATION OF LIABILITIES", "body": "The aggregate liability of the seller with respect to all claims arising out of or in connection with performance or non-performance of this contract whether in contract, warranty, tort or otherwise shall not exceed the contract price provided that this limitation shall not apply in case of negligence, willful misconduct or liabilities arising out of indemnity provisions in this contract.\n\n1) In no event other than buyer's default, seller shall be liable for any loss of profit or revenues, loss of production, loss of use of equipment or services or any associated equipment, interruption of business, or for any special, consequential incidental, indirect, punitive or exemplary damages.\n\n2) Seller's liability shall end upon expiration of the applicable warranty period."},
    {"number": "28", "title": "JURISDICTION", "body": "All suits, legal proceedings and arbitration award under this Contract shall be filed, entertained and decided in the Court of Delhi and the Courts in Delhi shall have the exclusive jurisdiction over all such disputes/claims."},
]

# Service and Supply use same structure with different scope/process text
# (will be filled in when client provides the actual text)
# SERVICE_ARTICLES_UPDATED -- 42-clause structure for civil/construction service POs
SERVICE_ARTICLES = [
    {
        "number": "1",
        "title": "Scope of Work",
        "body": "The Scope of Work is described in the annexures attached. {vendor_name} is advised that the scope mentioned is not limited to these annexures only, but also bound and executed with all terms and conditions of tender & agreement between PEEIPL and {vendor_name}.\n\nThe various jobs are to be executed as per Standard Specifications and guidelines of the Client/PEEIPL, which are forming part of the Contract between {vendor_name} and PEEIPL.\n\nAny work not specifically mentioned in the scope of work, but necessary for the satisfactory execution and completion of the assigned jobs, is deemed to be included in the Scope of Work to be executed by {vendor_name} within the specified time and the Work/Scope/contract value.\n\n{description}"
    },
    {
        "number": "2",
        "title": "Site Visit",
        "body": "{vendor_name} has already visited the site and made himself well acquainted with the location, area and related logistics and equipments for completing the specified works.\n\nSite: {site_name}\nDelivery Address: {delivery_address}"
    },
    {
        "number": "3",
        "title": "Value of the Work/Scope/Contract",
        "body": "The value of this Contract shall be INR {total_amount} ({total_amount_words}).\n\nThe payments shall be made by PEEIPL based on the unit rates and quantities and as per measurement of actual work executed at the project site.\n\nAny deduction made by the client due to poor performance of work by {vendor_name}, the same amount will be recovered from {vendor_name}'s bills."
    },
    {
        "number": "4",
        "title": "Rates and Escalation",
        "body": "The unit rates agreed upon shall remain firm and unchanged throughout the total period of execution of works under this work including the extended period, if any. This being firm and final price, no escalation is payable in future on any account whatsoever it may be."
    },
    {
        "number": "5",
        "title": "Income Tax",
        "body": "Income Tax (TDS), TCS and Labour Cess shall be deducted at applicable rate in accordance with the relevant laws from all payments made by PEEIPL. TDS certificates for the same shall be provided by PEEIPL."
    },
    {
        "number": "6",
        "title": "Royalties",
        "body": "{vendor_name} shall pay required royalties and fees, wherever applicable and shall submit proof/receipt of all such payments with PEEIPL along with Running Account (RA) Bills/invoices. {vendor_name} shall also procure, as required, all appropriate proprietary rights, licenses, agreements and permissions for materials, methods, processes, intellectual property incorporated into the works."
    },
    {
        "number": "7",
        "title": "Terms of Payment",
        "body": "7.1 Payment process: The Works shall be measured and remunerated according to the Main Contract. The BOQ rates are all inclusive for the execution of the Works by {vendor_name}.\n\n7.2 Payment of monthly and final invoices:\ni) All executed works will be certified by PEEIPL and payment released within 30 days after certification and submission of RA bills.\nii) Retention money @6% shall be withheld from each bill, released on successful completion after expiry of defect liability period.\niii) {vendor_name} shall submit proof/PF deposit Challan and other relevant documents with PEEIPL along with running account bills.\niv) At the time of submission of final certified invoice, {vendor_name} shall submit a declaration that there is no further claim under this LOI/Purchase order.\n\n{delivery_terms}"
    },
    {
        "number": "8",
        "title": "Taxes and Duties",
        "body": "8.1 BOQ rates are exclusive of all applicable taxes. {vendor_name} shall provide proof of GST registration, PAN etc. on award of contract. Any levy/penalty levied due to {vendor_name} to PEEIPL shall be recovered from {vendor_name}.\n\n8.2 Tax invoices are required for enabling PEEIPL to claim appropriate tax benefit.\n\n8.3 {vendor_name} shall be fully responsible for meeting all tax obligations and shall keep PEEIPL fully indemnified.\n\n8.4 TDS will be deducted at higher rate U/s 206AB, if {vendor_name} fails to file the ITR for last two years."
    },
    {
        "number": "9",
        "title": "Extra Items",
        "body": "i) If it is not similar item then rate will be derived from identical item of sub-contract.\nii) Rate for Extra item will be applicable from similar item of sub contract.\niii) If not possible to derive rate, it will be derived from the prevailing market rate plus 10% towards overhead and profit. CPWD norms will follow."
    },
    {
        "number": "10",
        "title": "Performance Guarantees",
        "body": "{warranty_terms}"
    },
    {
        "number": "11",
        "title": "Effective Date",
        "body": "Effective date of this Work/Scope shall be the date of this work/Scope. {vendor_name} shall proceed with the mobilization of personnel/workmen, materials, equipments, machinery etc. required for execution of the works assigned.\n\nRequired By: {required_by}"
    },
    {
        "number": "12",
        "title": "Reference Documents",
        "body": "The Contract between the Client and PEEIPL and the Standard Specifications and guidelines of Client/Consultant/PEEIPL which are forming part of the contract between {vendor_name} and PEEIPL and the owner, shall be the reference and guiding documents for all purposes."
    },
    {
        "number": "13",
        "title": "Sub-Contractor to Arrange Facilities at its Own Cost",
        "body": "{vendor_name} shall engage sufficient number of manpower/personnel/Engineer along with experienced and competent supervisors to ensure quality of work and smooth and uninterrupted progress of the works. {vendor_name} shall not be allowed to continue with the work in the absence of appointed supervisor.\n\n{vendor_name} shall ensure and arrange at its own cost the accommodation, transportation, boarding etc. for its manpower/personnel deployed for the execution of works."
    },
    {
        "number": "14",
        "title": "Manpower",
        "body": "{vendor_name} shall submit with PEEIPL, the proposed site organization to be set up for the execution of the work. A chart showing the manpower allocation and deployment to this job with specific job allocations shall be submitted by {vendor_name} to PEEIPL. {vendor_name} shall take prior approval from PEEIPL for any change in the allocation and deployment."
    },
    {
        "number": "15",
        "title": "Equipment and Machinery to be Deployed",
        "body": "{vendor_name} shall mobilize all required tools and machinery for execution of work. Mobilization Plan shall be prepared and monitored from time to time by {vendor_name}. {vendor_name} shall ensure to get fitness certificate for all its equipment and machinery from the Owner or the agency notified by the Owner."
    },
    {
        "number": "16",
        "title": "Licenses and Permits",
        "body": "{vendor_name} shall obtain at its own cost, all the licenses and permits required under the provisions of applicable Acts/Statutes, Regulations and rules for execution of various works under this WORK/Scope/contract.\n\n{vendor_name} shall obtain and keep valid license under the provisions of Contract Labour (Regulation and Abolition) Act, 1970 and other licenses wherever necessary.\n\n{vendor_name} shall submit to PEEIPL copies of all necessary licenses/permissions/permits before commencement of works."
    },
    {
        "number": "17",
        "title": "Insurance Cover/Policies",
        "body": "Before commencing execution of the Work, {vendor_name} shall insure against liability for loss of any material, equipment, machinery or physical damage, loss or injury arising out of the execution of the Works.\n\n(A) Contractor's All Risk Insurance Policy covering: entire WORK/Scope/Contract value, third party insurance, civil commotion/riots/war, earthquake, fire, and any other applicable insurance policy.\n\n(B) Policy to cover {vendor_name}'s liability under Workmen's Compensation Act 1923, Minimum Wages Act 1948, Contract Labour (Regulation and Abolition) Act 1970.\n\n(C) Insurance cover against damage or loss in respect of materials, equipment and/or work done. Limit of liability shall not be less than the value of such materials at any stage of the Contract."
    },
    {
        "number": "18",
        "title": "Sub-Contractor's Liability",
        "body": "{vendor_name} hereby assumes liability for and agrees to save PEEIPL harmless and indemnifies from every expense, liability or payment by reason of any injury (including death) to any person or damage to property suffered through any act or omission of {vendor_name}, his employees, workmen or from the conditions of the Site which is in the control of {vendor_name} for execution of the works."
    },
    {
        "number": "19",
        "title": "Compliances under Applicable Acts/Legislations, Rules and Regulations",
        "body": "(i) {vendor_name} shall abide by all Acts/statutes, Legislations/Rules and Regulations as applicable to the said WORK/Scope and ensure and pay wages to its workmen as per the Minimum Wages Act, 1948.\n(ii) {vendor_name} shall be entirely responsible for compliances of all applicable provisions under the Employees Provident Fund and Miscellaneous Provisions Act, 1952, Workman's Compensation Act, 1923 and other applicable Acts/statutes.\n(iii) {vendor_name} shall obtain comprehensive insurance cover for its entire manpower against any injury/death during execution of works.\n(iv) {vendor_name} shall indemnify and keep indemnified PEEIPL against all claims, liabilities and expenses arising out of default/breach of any statutory provisions.\n(v) {vendor_name} shall maintain statutory records viz. muster roll, payment register etc.\n(vi) {vendor_name} shall disburse wages in presence of authorized representative of PEEIPL.\n(vii) {vendor_name} shall submit with PEEIPL proof/challan pertaining to deposit of PF and other statutory payments."
    },
    {
        "number": "20",
        "title": "Health, Safety and Environment Related Regulations",
        "body": "(a) Healthy and hygienic Conditions: {vendor_name} shall ensure suitable welfare and hygiene arrangements at the site and shall follow applicable rules and regulations.\n\n(b) Safety of Site and Safety Equipments: {vendor_name} shall take full responsibility for the adequacy, stability and safety of all Site operations. {vendor_name} shall arrange sufficient helmets, safety boots/shoes and protective clothing for workmen.\n\n(c) Protection of Environment: {vendor_name} shall comply with all applicable environmental laws and regulations and shall ensure that the Site remains free from pollutants. Notwithstanding the above, {vendor_name} shall comply with all the directions and decisions of PEEIPL in this regard."
    },
    {
        "number": "21",
        "title": "Date of Commencement and Completion",
        "body": "Time being the essence of this contract, {vendor_name} shall ensure and be entirely responsible for completion of the entire works under this WORK/Scope within the agreed timeline from receipt of this LOI/work order and as per project schedule given by Project In-charge.\n\nRequired By: {required_by}"
    },
    {
        "number": "22",
        "title": "Liquidated Damages",
        "body": "Back-to-Back as per Agreement executed between PEEIPL and {vendor_name}.\n\n{penalty_clauses}"
    },
    {
        "number": "23",
        "title": "Professional Performance",
        "body": "{vendor_name} has warranted that it shall perform the WORK/Scope/Contract in a professional manner, using sound engineering principles, procedures and practices and with such care and diligence as are required by and in accordance with the standards of care customarily practiced by reputed and leading contractors. {vendor_name} represents that it has the required skills and capacity to perform the Services."
    },
    {
        "number": "24",
        "title": "Compliance to Specifications and Other Requirements",
        "body": "{vendor_name} shall comply with the standard specifications and other technical requirements for execution of the assigned work as defined and laid down by the Client/Consultant/PEEIPL. {vendor_name} shall also comply with Owner's/PEEIPL's inspection requirements and measurement instructions.\n\nAcceptance of any technical or specification deviation by {vendor_name} shall be subject to acceptance by PEEIPL. In case of non-acceptance, {vendor_name} shall execute the job without any deviations or extra time and cost implications to PEEIPL."
    },
    {
        "number": "25",
        "title": "Protection of Underground Utilities and Repair of Damages",
        "body": "PEEIPL shall provide all available details of underground utilities to {vendor_name}. {vendor_name} shall obtain plans and full details of all existing and planned underground utilities/services from the relevant Local Authorities. {vendor_name} shall be fully responsible for location and protection of all underground lines and structures.\n\nShould any damage occur, {vendor_name} shall immediately contact the concerned person/authority and repair work shall forthwith be carried out by {vendor_name} at its own expenses."
    },
    {
        "number": "26",
        "title": "Free Issue/Supply of Material",
        "body": "All free issue material, supplied to {vendor_name} by PEEIPL, shall be properly stored and handled by {vendor_name} and kept entirely separate for easy identification. {vendor_name} shall keep a proper record showing details of the materials issued from the storage area and the balance remaining available for use.\n\n{vendor_name} shall be solely responsible and liable for safe keeping and safe custody of all free issue material. Wastage limit of free issue materials shall be as per provision in the main Contract and CPWD norms.\n\nReconciliation will be done on monthly basis; additional wastage of material will be recovered from RA bills with 20% extra handling charges and applicable taxes."
    },
    {
        "number": "27",
        "title": "Subletting/Assignments",
        "body": "{vendor_name} shall not, without the prior written approval of PEEIPL, subject or assign to any other third party the whole or any portion of the work under this contract. If such approval is granted, {vendor_name} shall not be relieved of any of its obligations, duties and responsibility under this WORK/Scope/contract."
    },
    {
        "number": "28",
        "title": "Confidentiality",
        "body": "{vendor_name} understands and agrees to treat as strictly confidential all the technical data and information handed over by PEEIPL in terms of this WORK/Scope. {vendor_name} shall not disclose or reveal the technical data and information provided by PEEIPL to any third party except its employees, if essential and strictly on need-to-know basis.\n\nConfidentiality clause shall not be applicable in respect of information already in possession of either party prior to its disclosure."
    },
    {
        "number": "29",
        "title": "Defect Liability Period",
        "body": "Back-to-Back as per Agreement executed between PEEIPL and {vendor_name}.\n\n{warranty_terms}"
    },
    {
        "number": "30",
        "title": "Indemnification by the Sub-Contractor",
        "body": "{vendor_name} hereby agrees to indemnify and shall keep PEEIPL indemnified and harmless from and against any and all liabilities, losses, damages, costs, claims, actions, proceedings, expenses which may be suffered or incurred by PEEIPL as a result of any misrepresentation or breach of terms by {vendor_name} under this WORK/Scope."
    },
    {
        "number": "31",
        "title": "Supersession / Entire WORK/Scope/Contract",
        "body": "This WORK/Scope/Contract, including the Annexure(s) attached hereto, constitutes and represents the entire WORK/Scope/Contract between the parties and cancels and supersedes all prior understandings, letters, agreements, representations, statements, negotiations between the parties in respect of the matters dealt with herein."
    },
    {
        "number": "32",
        "title": "Amendments",
        "body": "No amendment, supplement, modification or clarification of this WORK/Scope/Contract shall be valid or binding unless set forth in writing and duly executed by the parties to this WORK/Scope/contract."
    },
    {
        "number": "33",
        "title": "Captions and Headings",
        "body": "Captions and Headings, as used herein, are for convenience of reference only and shall not be construed to limit or extend the language of the provisions to which such captions or Heading may refer in this WORK/Scope/Contract."
    },
    {
        "number": "34",
        "title": "Severability",
        "body": "If any provision of this WORK/Scope/contract is determined to be invalid or unenforceable in whole or in part, such invalidity or unenforceability shall attach only to such provision and the remaining provisions of the WORK/Scope/contract shall continue to remain in full force and effect."
    },
    {
        "number": "35",
        "title": "Force Majeure",
        "body": "The failure of a Party to fulfill any of its obligations under the WORK/Scope shall not be considered to be a breach or default insofar as such inability arises from an event of Force Majeure, i.e. fire, tempest, flood, earthquake, war, civil disturbances, change in government policies, violence of an army or mob or terrorist attack, caused not due to act/s or omission/s of the Party, provided that the Party:\n(a) has taken all reasonable precautions and due care; and\n(b) has informed the other Party as soon as possible about the occurrence of such an event.\n\nShould one or both the Parties be prevented from fulfilling their contractual obligations by a state of Force Majeure lasting continuously for a period of one month, both parties should consult with each other regarding future implementation of the WORK/Scope."
    },
    {
        "number": "36",
        "title": "PEEIPL's Right to Engage Another Sub-Contractor",
        "body": "In the event that {vendor_name} unjustifiably fails to complete the entire works or part of the works assigned within the agreed and specified period(s), PEEIPL shall have full right to engage other Sub contractor/deploy additional manpower/machinery and get the works executed and completed by such other Sub contractor at the sole cost and risk of {vendor_name}.\n\nFurther, {vendor_name} shall also be liable to pay to PEEIPL damages for such breach to the extent PEEIPL suffered the loss, without prejudice to any other rights or guarantees enforceable under this WORK/Scope/Contract."
    },
    {
        "number": "37",
        "title": "Suspension",
        "body": "i) {vendor_name} shall, if instructed in writing by PEEIPL, suspend the works or any part thereof for such period so ordered and shall not proceed until {vendor_name} shall have received a written instruction from PEEIPL to commence the works.\nii) Unless the reason of such suspension is the default of {vendor_name}, {vendor_name} shall be entitled to an adjustment of Time Schedule for that period.\niii) Upon suspension of the works, {vendor_name} shall exercise all reasonable efforts to preserve and safeguard the suspended works and continue to complete performance of the balance of the works, if applicable."
    },
    {
        "number": "38",
        "title": "Termination",
        "body": "PEEIPL shall have the right to terminate this WORK/Scope/contract by giving 7 (seven) days advance written notice to {vendor_name}, where {vendor_name} becomes bankrupt or where due to any act, deed or omission on the part of {vendor_name}, results in breach of any term and condition of this WORK/Scope or any default which being capable of cure has not been cured within ten days from the date of receipt of notice issued by PEEIPL to {vendor_name}."
    },
    {
        "number": "39",
        "title": "Address for Communication/Notice",
        "body": "All communications/notices between the parties shall be sent through Registered A/D Post/Courier service at the address of the parties:\n\ni) In case of communications to {vendor_name}:\nAttention: {vendor_contact}\n{delivery_address}\n\nii) In case of communications to PEEIPL:\nPassavant Energy & Environment India Pvt. Ltd.\nNavi Mumbai, India"
    },
    {
        "number": "40",
        "title": "General",
        "body": "a) {vendor_name} shall ensure that all its workmen deployed for execution of the work shall be in conformity with the applicable statutory provisions and laws enacted from time to time by the Government.\n\nb) PEEIPL and {vendor_name} have entered into this contract on Principal-to-Principal basis and nothing stated herein shall be deemed or construed as a partnership or as a joint venture or as an agency.\n\nc) Each party is and shall remain an Independent Party. None of the Party or any of its Affiliates shall be considered an agent of the other.\n\nd) Neither party shall be deemed to have waived any right under this WORK/Scope/contract, unless such party has delivered to the other party a written waiver signed by that party or its duly authorized signatory.\n\ne) Nothing in this WORK/Scope will preclude PEEIPL from having similar relationships with other Sub contractors."
    },
    {
        "number": "41",
        "title": "Dispute Mechanism",
        "body": "(a) Resolution/Settlement through mutual discussion and negotiation:\nIn the event of any dispute or difference arising out of or in connection with the WORK/Scope/contract, the Parties hereto shall at the first instance use their best efforts to settle such disputes or differences amicably by mutual discussion and negotiation.\n\n(b) Arbitration:\nIn case the amicable resolution or settlement is not reached within a period of 30 days, such dispute(s) or difference(s) shall be referred to a sole Arbitrator for settlement by way of arbitration in accordance with the provisions of the Arbitration and Conciliation Act 1996. The sole arbitrator shall be appointed by the mutual consent of both the parties. The decision of the Arbitrator shall be final and binding on both the Parties. The venue of such arbitration shall be at New Delhi."
    },
    {
        "number": "42",
        "title": "Jurisdiction",
        "body": "In case of any dispute arises between the Parties relating to the construction, meaning and operation of this WORK/Scope or breach thereof, the courts in Gurgaon alone shall have the Jurisdiction.\n\nThis LOI/work order is being issued and sent to {vendor_name} in duplicate; {vendor_name} is required to send to PEEIPL one copy of the LOI/work order together with all its attachments duly signed and stamped in token of their unconditional acceptance of the same. If signed copy is not received within 3 days of issuance of LOI/Work order, this LOI/Work order is deemed by PEEIPL to be accepted in its entirety by {vendor_name}.\n\n{special_conditions}"
    }
]
SUPPLY_ARTICLES  = [a.copy() for a in TECHNOLOGY_ARTICLES]

LOI_TEMPLATES = {
    "technology": TECHNOLOGY_ARTICLES,
    "service":    SERVICE_ARTICLES,
    "supply":     SUPPLY_ARTICLES,
}


def _amount_to_words(amount: float) -> str:
    """Convert a numeric INR amount to words (simplified, Indian system)."""
    try:
        amount = int(amount)
        if amount <= 0:
            return "Zero"
        crore  = amount // 10_000_000
        lakh   = (amount % 10_000_000) // 100_000
        thous  = (amount % 100_000) // 1000
        remain = amount % 1000
        parts = []
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight",
                "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen",
                "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty",
                "Sixty", "Seventy", "Eighty", "Ninety"]

        def below_100(n):
            if n < 20:
                return ones[n]
            return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()

        def below_1000(n):
            if n >= 100:
                return ones[n // 100] + " Hundred" + (" " + below_100(n % 100) if n % 100 else "")
            return below_100(n)

        if crore:
            parts.append(below_1000(crore) + " Crore")
        if lakh:
            parts.append(below_100(lakh) + " Lakh")
        if thous:
            parts.append(below_100(thous) + " Thousand")
        if remain:
            parts.append(below_1000(remain))
        return " ".join(parts) + " only"
    except Exception:
        return ""


class LOIService:

    @staticmethod
    def get_template_articles(po_type: str) -> list[dict]:
        """Return a copy of the articles for the given PO type."""
        return [
            {"number": a["number"], "title": a["title"], "body": a["body"]}
            for a in LOI_TEMPLATES.get(po_type, TECHNOLOGY_ARTICLES)
        ]

    @staticmethod
    def fill_articles(po_type: str, po_data: dict[str, Any]) -> list[dict]:
        """
        Fill placeholder variables in articles with actual PO data.
        Returns list of {number, title, body} dicts with placeholders replaced.
        """
        total = float(po_data.get("total_amount", 0))
        variables = {
            "vendor_name":        po_data.get("vendor_name", "[VENDOR NAME]"),
            "vendor_contact":     po_data.get("vendor_contact", "[VENDOR CONTACT]"),
            "po_number":          po_data.get("po_number", "[PO NUMBER]"),
            "total_amount":       f"INR {total:,.2f}",
            "total_amount_words": _amount_to_words(total),
            "description":        po_data.get("description", "[DESCRIPTION]"),
            "delivery_address":   po_data.get("delivery_address", "[DELIVERY ADDRESS]"),
            "required_by":        po_data.get("required_by", "[DATE]"),
            "penalty_clauses":    po_data.get("penalty_clauses") or "As per standard terms.",
            "delivery_terms":     po_data.get("delivery_terms") or "Within agreed timeline from the date of PO approval.",
            "warranty_terms":     po_data.get("warranty_terms") or "As per standard warranty terms.",
            "special_conditions": po_data.get("special_conditions") or "None.",
            "site_name":          po_data.get("site_name", "[SITE NAME]"),
        }
        filled = []
        for article in LOIService.get_template_articles(po_type):
            try:
                body = article["body"].format(**variables)
            except KeyError:
                body = article["body"]
            filled.append({
                "number": article["number"],
                "title":  article["title"],
                "body":   body,
            })
        return filled

    @staticmethod
    def generate_pdf(
        po_data: dict[str, Any],
        articles: list[dict],
    ) -> bytes:
        """
        Generate a formatted PDF LOI document using fpdf2.
        fpdf2 is already in requirements.txt (fpdf2==2.8.7).
        """
        try:
            from fpdf import FPDF
        except ImportError:
            raise RuntimeError("fpdf2 is not installed. Run: pip install fpdf2 --break-system-packages")

        class LOI_PDF(FPDF):
            def header(self):
                self.set_font("Helvetica", "B", 10)
                self.set_fill_color(240, 240, 240)
                self.cell(0, 8, "M/S. PASSAVANT ENERGY & ENVIRONMENT INDIA PVT. LTD.", border=1, fill=True, ln=True, align="C")
                self.set_font("Helvetica", "", 9)
                self.cell(0, 5, "Navi Mumbai, India", ln=True, align="C")
                self.ln(3)

            def footer(self):
                self.set_y(-15)
                self.set_font("Helvetica", "I", 8)
                self.cell(0, 10, f"Page {self.page_no()}", align="C")

        pdf = LOI_PDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.set_margins(20, 25, 20)
        pdf.add_page()

        vendor_name   = po_data.get("vendor_name", "[VENDOR NAME]")
        po_number     = po_data.get("po_number", "DRAFT")
        site_name     = po_data.get("site_name", "[SITE]")
        description   = po_data.get("description", "[DESCRIPTION]")
        vendor_contact = po_data.get("vendor_contact", "[CONTACT]")

        # PO meta
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, f"PO Number: {po_number}  |  Site: {site_name}", ln=True)
        pdf.ln(2)

        # Attn
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"Kind Attn: {vendor_contact}", ln=True)
        pdf.ln(2)

        # Subject
        pdf.set_font("Helvetica", "B", 10)
        subj = f"Subject: LOI for {description}"
        pdf.multi_cell(0, 6, subj)
        pdf.ln(3)

        # Intro
        pdf.set_font("Helvetica", "", 10)
        intro = (
            f"The contractor/buyer, Passavant Energy & Environment India Pvt. Ltd. (PEEIPL), "
            f"is pleased to issue this Letter of Intent to M/s {vendor_name} (the Seller) "
            f"subject to the terms and conditions set forth below."
        )
        pdf.multi_cell(0, 5, intro)
        pdf.ln(4)

        # Articles
        for article in articles:
            # Article heading
            pdf.set_font("Helvetica", "B", 10)
            heading = f"ARTICLE {article['number']} - {article['title']}"
            pdf.multi_cell(0, 6, heading)
            pdf.ln(1)

            # Article body - handle encoding issues gracefully
            pdf.set_font("Helvetica", "", 10)
            body = article.get("body", "")
            # fpdf2 handles UTF-8 but rupee symbol needs fallback
            body = body.replace("INR ", "INR ")
            try:
                pdf.multi_cell(0, 5, body)
            except Exception:
                pdf.multi_cell(0, 5, body.encode("latin-1", errors="replace").decode("latin-1"))
            pdf.ln(4)

        # Signing section
        pdf.ln(6)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 5, "Please sign and return a copy of this LOI as acceptance of the above terms.", ln=True)
        pdf.ln(8)

        # Two-column signing
        col_w = (pdf.w - pdf.l_margin - pdf.r_margin) / 2
        y_before = pdf.get_y()
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(col_w, 6, "For Passavant Energy & Environment India Pvt. Ltd.")
        pdf.cell(col_w, 6, f"For {vendor_name}", ln=True)
        pdf.ln(14)
        pdf.set_draw_color(0, 0, 0)
        x = pdf.l_margin
        pdf.line(x, pdf.get_y(), x + col_w - 5, pdf.get_y())
        pdf.line(x + col_w + 5, pdf.get_y(), x + col_w * 2, pdf.get_y())
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(col_w, 5, "Authorised Signatory")
        pdf.cell(col_w, 5, "Authorised Signatory", ln=True)

        from io import BytesIO
        buf = BytesIO()
        pdf.output(buf)
        return buf.getvalue()

    @staticmethod
    def generate_docx(
        po_data: dict[str, Any],
        articles: list[dict],
    ) -> bytes:
        """
        Generate a formatted Word DOCX LOI document.
        Uses python-docx (must be installed: pip install python-docx).
        """
        try:
            from docx import Document
            from docx.shared import Pt, Inches, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
        except ImportError:
            raise RuntimeError(
                "python-docx is not installed. "
                "Run: pip install python-docx --break-system-packages"
            )

        doc = Document()

        # Page margins
        for section in doc.sections:
            section.top_margin    = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin   = Inches(1.2)
            section.right_margin  = Inches(1.2)

        # Header - buyer info
        header_text = (
            "M/S. PASSAVANT ENERGY & ENVIRONMENT INDIA PVT. LTD.\n"
            "Navi Mumbai, India"
        )
        h = doc.add_paragraph(header_text)
        h.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for run in h.runs:
            run.bold = True
            run.font.size = Pt(11)

        doc.add_paragraph()

        # Attn & Subject
        vendor_name = po_data.get("vendor_name", "[VENDOR NAME]")
        doc.add_paragraph(f"Kind Attn: {po_data.get('vendor_contact', '[CONTACT]')}")

        subj = doc.add_paragraph()
        subj_run = subj.add_run(f"Subject: LOI for {po_data.get('description', '[DESCRIPTION]')}")
        subj_run.bold = True

        doc.add_paragraph()

        # Intro paragraph
        intro = (
            f"The contractor/buyer, Passavant Energy & Environment India Pvt. Ltd. (PEEIPL), "
            f"desiring that certain works pertaining to the project as described herein, "
            f"has entered into discussions with M/s {vendor_name} (the Seller). "
            f"Purchase Order: {po_data.get('po_number', '[PO NUMBER]')} | "
            f"Site: {po_data.get('site_name', '[SITE]')}"
        )
        doc.add_paragraph(intro)
        doc.add_paragraph()

        # Articles
        for article in articles:
            # Article heading
            heading = doc.add_paragraph()
            run = heading.add_run(
                f"ARTICLE {article['number']} - {article['title']}"
            )
            run.bold = True
            run.font.size = Pt(11)

            # Article body - split on newlines for readability
            for line in article["body"].split("\n"):
                p = doc.add_paragraph(line)
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after  = Pt(2)
            doc.add_paragraph()

        # Closing
        doc.add_paragraph(
            "Please sign and return a copy of this Letter of Intent as your acceptance "
            "of the above terms and conditions."
        )
        doc.add_paragraph()
        doc.add_paragraph("For Passavant Energy & Environment India Pvt. Ltd.")
        doc.add_paragraph("\n\nAuthorised Signatory")
        doc.add_paragraph()
        doc.add_paragraph(f"For {vendor_name}")
        doc.add_paragraph("\n\nAuthorised Signatory")

        buf = BytesIO()
        doc.save(buf)
        return buf.getvalue()

    @staticmethod
    def _build_html(po_data: dict[str, Any], articles: list[dict]) -> str:
        """Build the HTML that WeasyPrint renders to PDF."""
        vendor_name  = po_data.get("vendor_name", "[VENDOR NAME]")
        po_number    = po_data.get("po_number", "[PO NUMBER]")
        site_name    = po_data.get("site_name", "[SITE]")
        description  = po_data.get("description", "[DESCRIPTION]")
        vendor_contact = po_data.get("vendor_contact", "[CONTACT]")

        articles_html = ""
        for article in articles:
            body_html = article["body"].replace("\n\n", "</p><p>").replace("\n", "<br>")
            articles_html += f"""
            <div class="article">
                <div class="article-title">ARTICLE {article['number']} - {article['title']}</div>
                <p>{body_html}</p>
            </div>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {{
    margin: 2cm 2.5cm;
    size: A4;
  }}
  body {{
    font-family: 'Times New Roman', Times, serif;
    font-size: 11pt;
    line-height: 1.5;
    color: #000;
  }}
  .header-box {{
    border: 1px solid #000;
    padding: 14px 18px;
    margin-bottom: 18px;
  }}
  .company-name {{
    font-weight: bold;
    font-size: 12pt;
    text-transform: uppercase;
    margin-bottom: 4px;
  }}
  .company-address {{
    font-size: 10pt;
  }}
  .attn {{
    margin: 12px 0 4px;
    font-weight: bold;
  }}
  .subject {{
    font-weight: bold;
    font-size: 11pt;
    margin: 8px 0 14px;
  }}
  .intro {{
    margin-bottom: 14px;
    text-align: justify;
  }}
  .article {{
    margin-bottom: 14px;
    page-break-inside: avoid;
  }}
  .article-title {{
    font-weight: bold;
    font-size: 11pt;
    margin-bottom: 6px;
    text-transform: uppercase;
  }}
  p {{
    margin: 0 0 6px 0;
    text-align: justify;
  }}
  .signing {{
    margin-top: 30px;
    display: flex;
    justify-content: space-between;
  }}
  .sign-block {{
    width: 45%;
  }}
  .sign-line {{
    border-top: 1px solid #000;
    margin-top: 40px;
    padding-top: 4px;
    font-size: 10pt;
  }}
  .po-meta {{
    font-size: 10pt;
    color: #333;
    margin-bottom: 14px;
  }}
</style>
</head>
<body>
  <div class="header-box">
    <div class="company-name">M/S. Passavant Energy &amp; Environment India Pvt. Ltd.</div>
    <div class="company-address">Navi Mumbai, India</div>
  </div>

  <div class="po-meta">PO Number: {po_number} | Site: {site_name}</div>

  <div class="attn">Kind Attn: {vendor_contact}</div>

  <div class="subject">Subject: LOI for {description}</div>

  <div class="intro">
    The contractor/buyer, Passavant Energy &amp; Environment India Pvt. Ltd. (PEEIPL),
    desiring that certain works pertaining to the project as described herein,
    has entered into discussions with M/s <strong>{vendor_name}</strong> (the Seller)
    and is pleased to issue this Letter of Intent subject to the terms and conditions set
    forth below.
  </div>

  {articles_html}

  <div style="margin-top:30px;">
    <p>Please sign and return a copy of this Letter of Intent as your acceptance of the
    above terms and conditions.</p>
  </div>

  <table style="width:100%;margin-top:40px;">
    <tr>
      <td style="width:50%;vertical-align:top;">
        <p><strong>For Passavant Energy &amp; Environment India Pvt. Ltd.</strong></p>
        <br><br><br>
        <div style="border-top:1px solid #000;padding-top:4px;font-size:10pt;">Authorised Signatory</div>
      </td>
      <td style="width:50%;vertical-align:top;padding-left:30px;">
        <p><strong>For {vendor_name}</strong></p>
        <br><br><br>
        <div style="border-top:1px solid #000;padding-top:4px;font-size:10pt;">Authorised Signatory</div>
      </td>
    </tr>
  </table>

</body>
</html>"""
