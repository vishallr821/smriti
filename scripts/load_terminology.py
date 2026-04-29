"""Load minimal terminology subsets into terminology_index."""

from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urlparse

import asyncpg
import numpy as np
from sentence_transformers import SentenceTransformer

SNOMED_TERMS = [
    ("44054006", "Type 2 diabetes mellitus", ["T2DM", "Adult onset diabetes"]),
    ("38341003", "Essential hypertension", ["HTN", "High blood pressure"]),
    ("13644009", "Hypercholesterolemia", ["High cholesterol", "Dyslipidemia"]),
    ("195967001", "Asthma", ["Reactive airway disease"]),
    ("13645005", "Chronic obstructive pulmonary disease", ["COPD"]),
    ("53741008", "Coronary arteriosclerosis", ["CAD", "Coronary artery disease"]),
    ("230690007", "Cerebrovascular accident", ["Stroke"]),
    ("363346000", "Malignant neoplastic disease", ["Cancer"]),
    ("73211009", "Diabetes mellitus", ["DM"]),
    ("709044004", "Chronic kidney disease", ["CKD"]),
    ("233678006", "Hypothyroidism", ["Underactive thyroid"]),
    ("300916003", "Gastroesophageal reflux disease", ["GERD", "Acid reflux"]),
    ("4834000", "Urinary tract infectious disease", ["UTI"]),
    ("49601007", "Disorder of liver", ["Liver disease"]),
    ("239873007", "Osteoarthritis", ["OA"]),
    ("24700007", "Multiple sclerosis", ["MS"]),
    ("69896004", "Rheumatoid arthritis", ["RA"]),
    ("35489007", "Depressive disorder", ["Depression"]),
    ("197480006", "Anxiety disorder", ["Anxiety"]),
    ("111570005", "Obesity", ["High BMI"]),
    ("414916001", "Obstructive sleep apnea syndrome", ["OSA"]),
    ("389145006", "Allergic rhinitis", ["Hay fever"]),
    ("36971009", "Sinusitis", ["Rhinosinusitis"]),
    ("278860009", "Chronic low back pain", ["Back pain"]),
    ("84757009", "Myocardial infarction", ["Heart attack"]),
    ("49436004", "Atrial fibrillation", ["AF"]),
    ("67362008", "Migraine", ["Migraine headache"]),
    ("422034002", "Prediabetes", ["Impaired glucose tolerance"]),
    ("444814009", "Viral upper respiratory tract infection", ["Common cold"]),
    ("128302006", "Anemia", ["Low hemoglobin"]),
    ("410429000", "Acute bronchitis", ["Bronchitis"]),
    ("363406005", "Malignant tumor of breast", ["Breast cancer"]),
    ("363443007", "Malignant tumor of prostate", ["Prostate cancer"]),
    ("429040005", "Nonalcoholic fatty liver disease", ["NAFLD"]),
    ("312912005", "Kidney stone", ["Renal calculus"]),
    ("386661006", "Fever", ["Pyrexia"]),
    ("25064002", "Headache", ["Cephalgia"]),
    ("422587007", "Nausea", ["Queasiness"]),
    ("62315008", "Diarrhea", ["Loose stools"]),
    ("267036007", "Dyspnea", ["Shortness of breath"]),
    ("49727002", "Cough", ["Persistent cough"]),
    ("22298006", "Myocarditis", ["Cardiac inflammation"]),
    ("441457006", "Anaphylaxis", ["Severe allergy"]),
    ("30746006", "Psoriasis", ["Psoriatic skin disease"]),
    ("396275006", "Osteoporosis", ["Low bone density"]),
    ("11687002", "Obstipation", ["Constipation"]),
    ("271327008", "Skin rash", ["Dermatitis"]),
    ("400047006", "Chronic pain", ["Persistent pain"]),
    ("162864005", "Body mass index 30+ - obesity", ["BMI obesity"]),
    ("15777000", "Predominant disturbance of emotions", ["Mood disorder"]),
]

LOINC_TERMS = [
    ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood", ["HbA1c", "Glycated hemoglobin"]),
    ("718-7", "Hemoglobin [Mass/volume] in Blood", ["Hemoglobin"]),
    ("789-8", "Erythrocytes [#/volume] in Blood", ["RBC count"]),
    ("6690-2", "Leukocytes [#/volume] in Blood", ["WBC count"]),
    ("777-3", "Platelets [#/volume] in Blood", ["Platelet count"]),
    ("785-6", "MCH [Entitic mass] by Automated count", ["MCH"]),
    ("787-2", "MCV [Entitic volume] by Automated count", ["MCV"]),
    ("788-0", "MCHC [Mass/volume] by Automated count", ["MCHC"]),
    ("5902-2", "Prothrombin time (PT)", ["PT"]),
    ("6301-6", "INR in Platelet poor plasma", ["INR"]),
    ("2345-7", "Glucose [Mass/volume] in Serum", ["Serum glucose"]),
    ("2951-2", "Sodium [Moles/volume] in Serum", ["Sodium"]),
    ("2823-3", "Potassium [Moles/volume] in Serum", ["Potassium"]),
    ("2075-0", "Chloride [Moles/volume] in Serum", ["Chloride"]),
    ("2028-9", "Carbon dioxide, total [Moles/volume] in Serum", ["Bicarbonate"]),
    ("3094-0", "Urea nitrogen [Mass/volume] in Serum", ["BUN"]),
    ("2160-0", "Creatinine [Mass/volume] in Serum", ["Creatinine"]),
    ("14682-9", "Estimated GFR", ["eGFR"]),
    ("1920-8", "Aspartate aminotransferase [Enzymatic activity/volume]", ["AST"]),
    ("1742-6", "Alanine aminotransferase [Enzymatic activity/volume]", ["ALT"]),
    ("6768-6", "Alkaline phosphatase [Enzymatic activity/volume]", ["ALP"]),
    ("1975-2", "Bilirubin.total [Mass/volume] in Serum", ["Total bilirubin"]),
    ("2885-2", "Protein [Mass/volume] in Serum", ["Total protein"]),
    ("1751-7", "Albumin [Mass/volume] in Serum", ["Albumin"]),
    ("2085-9", "Cholesterol in HDL [Mass/volume] in Serum", ["HDL"]),
    ("13457-7", "Cholesterol in LDL [Mass/volume] in Serum", ["LDL"]),
    ("2571-8", "Triglyceride [Mass/volume] in Serum", ["Triglycerides"]),
    ("2093-3", "Cholesterol [Mass/volume] in Serum", ["Total cholesterol"]),
    ("3016-3", "Thyrotropin [Units/volume] in Serum", ["TSH"]),
    ("3024-7", "Thyroxine (T4) free [Mass/volume] in Serum", ["Free T4"]),
]

ICD10_TERMS = [
    ("E11", "Type 2 diabetes mellitus", ["T2DM"]),
    ("I10", "Essential hypertension", ["HTN"]),
    ("E78.0", "Pure hypercholesterolemia", ["High cholesterol"]),
    ("J45", "Asthma", ["Bronchial asthma"]),
    ("J44", "Chronic obstructive pulmonary disease", ["COPD"]),
    ("I25.1", "Atherosclerotic heart disease", ["CAD"]),
    ("I63", "Cerebral infarction", ["Stroke"]),
    ("N18", "Chronic kidney disease", ["CKD"]),
    ("E03.9", "Hypothyroidism, unspecified", ["Hypothyroidism"]),
    ("K21.9", "Gastro-esophageal reflux disease", ["GERD"]),
    ("N39.0", "Urinary tract infection", ["UTI"]),
    ("K76.0", "Fatty (change of) liver", ["Fatty liver"]),
    ("M19.9", "Osteoarthritis, unspecified", ["OA"]),
    ("M06.9", "Rheumatoid arthritis, unspecified", ["RA"]),
    ("F32.9", "Depressive episode, unspecified", ["Depression"]),
    ("F41.9", "Anxiety disorder, unspecified", ["Anxiety"]),
    ("E66.9", "Obesity, unspecified", ["Obesity"]),
    ("G47.33", "Obstructive sleep apnea", ["OSA"]),
    ("J30.9", "Allergic rhinitis", ["Rhinitis"]),
    ("J32.9", "Chronic sinusitis", ["Sinusitis"]),
    ("M54.5", "Low back pain", ["Back pain"]),
    ("I21.9", "Acute myocardial infarction", ["MI"]),
    ("I48.91", "Unspecified atrial fibrillation", ["AF"]),
    ("G43.9", "Migraine", ["Migraine headache"]),
    ("R73.03", "Prediabetes", ["Impaired glucose"]),
    ("J06.9", "Acute upper respiratory infection", ["URI"]),
    ("D64.9", "Anemia, unspecified", ["Anemia"]),
    ("J20.9", "Acute bronchitis", ["Bronchitis"]),
    ("C50.9", "Malignant neoplasm of breast", ["Breast cancer"]),
    ("C61", "Malignant neoplasm of prostate", ["Prostate cancer"]),
    ("K76.9", "Liver disease, unspecified", ["Liver disease"]),
    ("N20.0", "Calculus of kidney", ["Kidney stone"]),
    ("R50.9", "Fever, unspecified", ["Fever"]),
    ("R51", "Headache", ["Headache"]),
    ("R11.0", "Nausea", ["Nausea"]),
    ("R19.7", "Diarrhea", ["Diarrhea"]),
    ("R06.0", "Dyspnea", ["Shortness of breath"]),
    ("R05", "Cough", ["Cough"]),
    ("T78.2", "Anaphylactic shock", ["Anaphylaxis"]),
    ("L40.9", "Psoriasis, unspecified", ["Psoriasis"]),
    ("M81.0", "Age-related osteoporosis", ["Osteoporosis"]),
    ("K59.0", "Constipation", ["Constipation"]),
    ("R21", "Rash and other skin eruption", ["Skin rash"]),
    ("G89.4", "Chronic pain syndrome", ["Chronic pain"]),
    ("E78.5", "Hyperlipidemia, unspecified", ["Hyperlipidemia"]),
    ("I50.9", "Heart failure, unspecified", ["Heart failure"]),
    ("J18.9", "Pneumonia, unspecified", ["Pneumonia"]),
    ("A09", "Infectious gastroenteritis", ["GE"]),
    ("L03.90", "Cellulitis", ["Cellulitis"]),
    ("N40.0", "Benign prostatic hyperplasia", ["BPH"]),
]

RXNORM_COMMON_MEDS = [
    "Metformin", "Atorvastatin", "Lisinopril", "Amlodipine", "Losartan", "Telmisartan",
    "Hydrochlorothiazide", "Furosemide", "Spironolactone", "Aspirin", "Clopidogrel",
    "Rosuvastatin", "Simvastatin", "Levothyroxine", "Pantoprazole", "Omeprazole",
    "Esomeprazole", "Rabeprazole", "Paracetamol", "Ibuprofen", "Diclofenac", "Naproxen",
    "Tramadol", "Pregabalin", "Gabapentin", "Amoxicillin", "Azithromycin", "Cefixime",
    "Ceftriaxone", "Levofloxacin", "Doxycycline", "Ciprofloxacin", "Metronidazole",
    "Insulin glargine", "Insulin aspart", "Insulin lispro", "Glimepiride", "Gliclazide",
    "Sitagliptin", "Vildagliptin", "Teneligliptin", "Empagliflozin", "Dapagliflozin",
    "Canagliflozin", "Semaglutide", "Liraglutide", "Dulaglutide", "Pioglitazone",
    "Linagliptin", "Acarbose", "Carvedilol", "Metoprolol", "Bisoprolol", "Nebivolol",
    "Diltiazem", "Verapamil", "Digoxin", "Nitroglycerin", "Isosorbide mononitrate",
    "Warfarin", "Apixaban", "Rivaroxaban", "Dabigatran", "Heparin", "Enoxaparin",
    "Sertraline", "Escitalopram", "Fluoxetine", "Duloxetine", "Venlafaxine", "Mirtazapine",
    "Clonazepam", "Alprazolam", "Lorazepam", "Quetiapine", "Olanzapine", "Risperidone",
    "Montelukast", "Cetirizine", "Levocetirizine", "Fexofenadine", "Salbutamol",
    "Budesonide", "Formoterol", "Tiotropium", "Ipratropium", "Theophylline", "Prednisolone",
    "Methotrexate", "Hydroxychloroquine", "Sulfasalazine", "Allopurinol", "Colchicine",
    "Ferrous sulfate", "Vitamin D3", "Calcium carbonate", "Cyanocobalamin", "Folic acid",
    "Zinc sulfate", "Multivitamin",
]

RXNORM_TERMS = [
    (f"RX{idx:04d}", name, [name.lower(), f"{name} tablet"])
    for idx, name in enumerate(RXNORM_COMMON_MEDS, start=1)
]


def _is_pooler_dsn(dsn: str) -> bool:
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    return "pooler.supabase.com" in host or parsed.port == 6543


def _resolve_dsn() -> str:
    dsn = os.getenv("SUPABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("SUPABASE_URL is required")
    if not dsn.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("SUPABASE_URL must be a Postgres connection string")
    return dsn


def _vector_literal(vector: np.ndarray) -> str:
    values = ",".join(f"{float(v):.8f}" for v in vector.tolist())
    return f"[{values}]"


async def _insert_system_terms(
    connection: asyncpg.Connection,
    model: SentenceTransformer,
    system: str,
    terms: list[tuple[str, str, list[str]]],
) -> None:
    existing = await connection.fetchval(
        "SELECT COUNT(*) FROM terminology_index WHERE system = $1", system
    )
    assert isinstance(existing, int)
    if existing > 0:
        print(f"{system}: already seeded, skipping")
        return

    texts = [f"{display_name}. Synonyms: {', '.join(synonyms)}" for _, display_name, synonyms in terms]
    vectors = model.encode(texts, show_progress_bar=False)

    async with connection.transaction():
        for (code, display_name, synonyms), vec in zip(terms, vectors):
            await connection.execute(
                """
                INSERT INTO terminology_index (system, code, display_name, synonyms, embedding)
                VALUES ($1, $2, $3, $4::text[], $5::vector)
                ON CONFLICT (system, code) DO NOTHING
                """,
                system,
                code,
                display_name,
                synonyms,
                _vector_literal(np.asarray(vec, dtype=np.float32)),
            )

    print(f"{system}: inserted {len(terms)} terms")


async def load_terminology() -> None:
    np.random.seed(42)

    if len(SNOMED_TERMS) != 50:
        raise RuntimeError("SNOMED subset must contain exactly 50 terms")
    if len(LOINC_TERMS) != 30:
        raise RuntimeError("LOINC subset must contain exactly 30 terms")
    if len(ICD10_TERMS) != 50:
        raise RuntimeError("ICD-10 subset must contain exactly 50 terms")
    if len(RXNORM_TERMS) != 100:
        raise RuntimeError("RxNorm subset must contain exactly 100 terms")

    dsn = _resolve_dsn()
    connect_kwargs: dict[str, object] = {"dsn": dsn}
    if _is_pooler_dsn(dsn):
        connect_kwargs["statement_cache_size"] = 0

    model = SentenceTransformer("all-MiniLM-L6-v2")
    connection = await asyncpg.connect(**connect_kwargs)
    try:
        await _insert_system_terms(connection, model, "snomed", SNOMED_TERMS)
        await _insert_system_terms(connection, model, "loinc", LOINC_TERMS)
        await _insert_system_terms(connection, model, "icd10", ICD10_TERMS)
        await _insert_system_terms(connection, model, "rxnorm", RXNORM_TERMS)

        totals = await connection.fetch(
            """
            SELECT system, COUNT(*) AS n
            FROM terminology_index
            GROUP BY system
            ORDER BY system
            """
        )
        print("terminology_index row count by system:")
        for row in totals:
            print(f"  {row['system']}: {int(row['n'])}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(load_terminology())
