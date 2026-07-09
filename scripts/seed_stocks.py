"""
Seed EGX stocks into the database.
Run: python scripts/seed_stocks.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app, db
from app.models.stock import Stock

EGX_STOCKS = [
    # Symbol   name_ar                                    name_en                                  Sector                  Sharia
    # ── البنوك ──────────────────────────────────────────────────────────────────────────────────────────────────
    ("COMI",  "البنك التجاري الدولي",                   "Commercial International Bank",          "البنوك",               False),
    ("CIEB",  "بنك CIB",                                "CIB",                                    "البنوك",               False),
    ("QNBE",  "بنك قطر الوطني الأهلي",                 "QNB Alahli",                             "البنوك",               False),
    ("ADIB",  "بنك أبوظبي الإسلامي - مصر",            "Abu Dhabi Islamic Bank Egypt",           "البنوك",               True),
    ("ARCC",  "بنك العربي",                             "Arab Banking Corporation",               "البنوك",               False),
    ("FAITA", "فايبا الاستثمار",                       "FAITA",                                  "البنوك",               False),
    ("AIBD",  "بنك الاستثمار العربي",                  "Arab Investment Bank",                   "البنوك",               False),
    ("MISR",  "بنك مصر",                                "Banque Misr",                            "البنوك",               False),
    ("NBGE",  "البنك الأهلي المصري",                   "National Bank of Egypt",                 "البنوك",               False),
    # ── العقارات ────────────────────────────────────────────────────────────────────────────────────────────────
    ("TMGH",  "طلعت مصطفى القابضة",                   "Talaat Moustafa Group",                  "العقارات",             False),
    ("MASR",  "مدينة مصر للإسكان والتعمير",           "Madinet Masr",                           "العقارات",             False),
    ("PHDC",  "بالم هيلز للتطوير",                    "Palm Hills Developments",                "العقارات",             False),
    ("MNHD",  "مدينة نصر للإسكان والتعمير",           "Madinet Nasr Housing",                   "العقارات",             False),
    ("OCDI",  "أوراسكوم للتطوير",                     "Orascom Development",                    "العقارات",             False),
    ("CLHO",  "سيتي إيدج للتطوير العقاري",            "City Edge Developments",                 "العقارات",             False),
    ("SWDY",  "شركة سوديك",                           "SODIC",                                  "العقارات",             False),
    ("RREI",  "ريدكون للعقارات",                      "Redcon for Real Estate",                 "العقارات",             False),
    ("ORHD",  "أوراسكوم للتشييد",                    "Orascom Housing",                        "العقارات",             False),
    ("OBRI",  "أوراسكوم للإنشاء والصناعة",           "Orascom Construction",                   "التشييد والبناء",      False),
    # ── الأدوية والرعاية الصحية ─────────────────────────────────────────────────────────────────────────────────
    ("ISPH",  "مستشفيات المقاولون العرب",             "ISPH",                                   "الرعاية الصحية",       False),
    ("EFIH",  "هيرميس القابضة",                       "EFG Hermes Holding",                     "المالية",              False),
    ("EFID",  "العربي الأفريقي للتأمين",              "EFG Hermes",                             "المالية",              False),
    ("OCPH",  "المصرية للأدوية",                      "October Pharma",                         "الأدوية",              False),
    ("BIOC",  "بيوكيم فارما",                         "Bioc Pharma",                            "الأدوية",              False),
    ("ISMA",  "إسنا للأدوية",                         "Isna Pharma",                            "الأدوية",              False),
    ("MFPC",  "فارماكير للأدوية",                    "Pharma Care",                            "الأدوية",              False),
    ("MPCO",  "مصر للصناعات الدوائية",               "Egyptian Pharmaceutical Industries",     "الأدوية",              False),
    ("EGCH",  "إيجيبت كير للرعاية الصحية",           "Egypt Care",                             "الرعاية الصحية",       False),
    # ── البتروكيماويات والطاقة ───────────────────────────────────────────────────────────────────────────────────
    ("AMOC",  "الإسكندرية لزيوت المعادن",            "Alexandria Mineral Oils",                "البتروكيماويات",       False),
    ("SKPC",  "سيدي كرير للبتروكيماويات",            "Sidi Kerir Petrochemicals",              "البتروكيماويات",       True),
    ("EGAS",  "بوتاجاسكو",                            "EGAS",                                   "الطاقة",               False),
    ("KABO",  "مصر الوسطى لتوزيع الغاز",            "Cairo Gas",                              "الطاقة",               False),
    ("ABUK",  "أبوقير للأسمدة والصناعات الكيماوية", "Abu Qir Fertilizers",                    "الصناعات الكيماوية",   True),
    ("KIMA",  "كيما - أسوان للأسمدة",               "Kima",                                   "الصناعات الكيماوية",   False),
    # ── الغذاء والشراب ──────────────────────────────────────────────────────────────────────────────────────────
    ("JUFO",  "جهينة للأغذية",                       "Juhayna Food Industries",                "الغذاء والشراب",       True),
    ("SAUD",  "السعودي المصري للتعمير",              "Saudi Egyptian Construction",             "الغذاء والشراب",       False),
    ("POUL",  "قها للدواجن",                          "Cairo Poultry",                          "الغذاء والشراب",       True),
    ("DOMT",  "دومتي",                               "Domty",                                  "الغذاء والشراب",       False),
    ("AMER",  "أمريكانا ريستورانتس",                 "Americana Restaurants",                  "الغذاء والشراب",       True),
    ("SPIN",  "سبينيس مصر",                          "Spinneys Egypt",                         "التجزئة",              False),
    ("AJWA",  "عجوة للصناعات الغذائية",              "Ajwa Food Industries",                   "الغذاء والشراب",       True),
    ("AMES",  "أميس للصناعات الغذائية",              "Ames Food",                              "الغذاء والشراب",       False),
    # ── الاتصالات والتكنولوجيا ──────────────────────────────────────────────────────────────────────────────────
    ("ETEL",  "المصرية للاتصالات",                   "Telecom Egypt",                          "الاتصالات",            False),
    ("ETRS",  "إي فاينانس",                          "e-Finance",                              "التكنولوجيا",          False),
    ("FWRY",  "فوري للتكنولوجيا والمدفوعات",         "Fawry",                                  "التكنولوجيا",          False),
    ("GTHE",  "شركة جرين تك",                        "GreenTech",                              "التكنولوجيا",          False),
    ("INFI",  "انفينيتي للطاقة المتجددة",            "Infinity EV",                            "التكنولوجيا",          False),
    ("MKIT",  "ميدكت للتكنولوجيا",                  "Medkit",                                 "التكنولوجيا",          False),
    ("MCRO",  "مكرو للخدمات",                        "Macro Services",                         "التكنولوجيا",          False),
    # ── الصناعات الأساسية والمواد ───────────────────────────────────────────────────────────────────────────────
    ("IRON",  "الإسكندرية للحديد والصلب",            "Alexandria National Iron & Steel",       "الصناعات الأساسية",    False),
    ("ISGC",  "الإسكندرية للزجاج والكريستال",        "International Glass",                    "مواد البناء",          False),
    ("MMAT",  "مصر للألومنيوم",                      "Egyptian Aluminum",                      "الصناعات الأساسية",    False),
    ("SCFM",  "السويس للأسمنت",                      "Suez Cement",                            "مواد البناء",          False),
    ("SCEM",  "إسكندرية للإسمنت",                   "Alexandria Cement",                      "مواد البناء",          False),
    ("CAED",  "القاهرة للإسمنت",                    "Cairo Cement",                           "مواد البناء",          False),
    ("MICH",  "ميشيل للمنتجات المعدنية",            "Michel Metal",                           "الصناعات الأساسية",    False),
    # ── الاستثمار والمالية ──────────────────────────────────────────────────────────────────────────────────────
    ("ORWE",  "أوراسكوم للاستثمار",                  "Orascom Investment Holding",             "الاستثمار",            False),
    ("HRHO",  "هيرميس القابضة",                      "Hermes Holding",                         "المالية",              False),
    ("ACGC",  "العربي للمقاولات",                    "Arab Contractors",                       "التشييد والبناء",      False),
    ("GIHD",  "جي آي القابضة",                       "GI Holdings",                            "الاستثمار",            False),
    ("ATQA",  "أتقان للاستثمار",                    "Atqa Investment",                        "الاستثمار",            False),
    ("RACC",  "ريدكون للإنشاء",                     "Redcon Construction",                    "التشييد والبناء",      False),
    ("EGAL",  "إيغل للأسمنت",                       "Eagle Cement",                           "مواد البناء",          False),
    ("GMCI",  "جرانيت مصر",                         "Granite Egypt",                          "مواد البناء",          False),
    ("MBSC",  "مصر بازل للمقاولات",                 "Misr Basel",                             "التشييد والبناء",      False),
    ("PRCL",  "بياضة ريدكون للمقاولات",             "Precal",                                 "التشييد والبناء",      False),
    # ── المتنوع ─────────────────────────────────────────────────────────────────────────────────────────────────
    ("MCQE",  "ماكرو للصحة والجمال",                "Macro Group",                            "التجزئة",              False),
    ("ALCN",  "الكان للصناعة",                       "Alkan",                                  "الصناعات الهندسية",    False),
    ("ORAS",  "أوراسكوم للإنشاء",                   "Orascom Construction",                   "التشييد والبناء",      False),
    ("MTIE",  "متى للصناعة والتجارة",               "Maty Industries",                        "الصناعات الهندسية",    False),
    ("ICFC",  "المصرية للإسكان والتعمير",           "Intl Company for Finance",               "المالية",              False),
    ("IFAP",  "إيفاب للاستثمار",                    "IFAP Investment",                        "الاستثمار",            False),
    ("RMDA",  "رمادا للفنادق",                       "Ramada Hotels",                          "السياحة والترفيه",     False),
    ("OLFI",  "أوليفي للصناعات الغذائية",           "Olivia Food",                            "الغذاء والشراب",       False),
    ("LCSW",  "لوكسور للإسمنت",                    "Luxor Cement",                           "مواد البناء",          False),
    ("FNAR",  "فنار مصر",                           "Fnar Egypt",                             "المتنوع",              False),
    ("NCCW",  "المصرية للاتصالات الجديدة",          "NCCW",                                   "الاتصالات",            False),
    ("EHDR",  "إيهدر للطاقة",                       "Ehdr Energy",                            "الطاقة",               False),
    ("SIPC",  "سيناء للتنمية",                      "Sinai Development",                      "الاستثمار",            False),
    ("MPCI",  "المصرية للمقاولات",                  "Egyptian Contractors",                   "التشييد والبناء",      False),
    ("CPCI",  "القاهرة للاستثمار",                  "Cairo Investment",                       "الاستثمار",            False),
    ("NINH",  "النيل للفنادق والسياحة",             "Nile Hotels",                            "السياحة والترفيه",     False),
    ("ADRI",  "أدريان مصر",                         "Adrian Egypt",                           "المتنوع",              False),
    ("BIGP",  "بيج بويز للترفيه",                  "Big Boys",                               "السياحة والترفيه",     False),
    ("EDFM",  "ايدفو للمناجم",                     "Edfu Mines",                             "التعدين",              False),
    ("MILS",  "مصر لتجارة الجملة",                 "Misr Wholesale",                         "التجارة",              False),
    ("AFMC",  "أفريكانا المصرية",                  "Africana Egypt",                         "الغذاء والشراب",       False),
    ("ELNA",  "إلنا للصناعة",                      "Elna Industries",                        "الصناعات الهندسية",    False),
    ("MOSC",  "موسكو للاستثمار",                   "Moscow Investment",                      "الاستثمار",            False),
    ("MOED",  "مود للملابس",                        "Moed Fashion",                           "الملابس والنسيج",      False),
    ("AALR",  "الأهلي للتأجير التمويلي",           "Ahli Leasing",                           "المالية",              False),
    ("ACAMD", "أكاديمية القاهرة للفنون",           "Cairo Academy",                          "التعليم",              False),
    ("AIFI",  "الاتحاد المصري للتأمين",            "Egyptian Insurance Union",               "التأمين",              False),
    ("AMPI",  "أمبي فارما",                        "AMPI Pharma",                            "الأدوية",              False),
    ("APSW",  "أبسو للمياه",                       "APSW Water",                             "المرافق",              False),
    ("ARVA",  "أرفى للاستثمار",                   "Arva Investment",                        "الاستثمار",            False),
    ("ATLC",  "أطلس للاستثمار",                   "Atlas Investment",                       "الاستثمار",            False),
    ("BIDI",  "بيدي للصناعة",                     "Bidi Industries",                        "الصناعات الهندسية",    False),
    ("EALR",  "الأهلي للتأجير",                   "Ahli Leasing 2",                         "المالية",              False),
    ("IEEC",  "مصر للطاقة الكهربائية",            "Egyptian Electrical",                    "الطاقة",               False),
    ("INEG",  "أنيرجي",                            "Inergy",                                 "الطاقة",               False),
    ("ISMQ",  "إسماعيلية للمياه",                 "Ismailia Water",                         "المرافق",              False),
    ("MBSC",  "مصر بازل",                          "Misr Basel Construction",               "التشييد والبناء",      False),
    ("NEDA",  "ندى للاستثمار",                    "Neda Investment",                        "الاستثمار",            False),
    ("RUBX",  "روبكس للصناعة",                    "Rubex Industries",                       "الصناعات الهندسية",    False),
    ("FAIT",  "فايت للاستثمار",                   "FAIT Investment",                        "الاستثمار",            False),
    ("FIRE",  "فايرستون",                          "Firestone Egypt",                        "الصناعات الأساسية",    False),
    ("MMAT",  "مصر للألومنيوم",                   "Egyptian Aluminum",                      "الصناعات الأساسية",    False),
]


def seed():
    app = create_app()
    with app.app_context():
        db.create_all()
        added = skipped = updated = 0

        seen = set()
        for symbol, name_ar, name_en, sector, is_sharia in EGX_STOCKS:
            if symbol in seen:
                continue
            seen.add(symbol)

            existing = Stock.query.filter_by(symbol=symbol).first()
            if existing:
                if existing.name_ar == symbol:
                    existing.name_ar  = name_ar
                    existing.name_en  = name_en
                    existing.sector   = sector
                    existing.is_sharia = is_sharia
                    updated += 1
                else:
                    skipped += 1
                continue

            db.session.add(Stock(
                symbol    = symbol,
                name_ar   = name_ar,
                name_en   = name_en,
                sector    = sector,
                is_sharia = is_sharia,
                is_active = True,
            ))
            added += 1

        db.session.commit()
        print(f"Seed complete: {added} added, {updated} updated, {skipped} already existed.")


if __name__ == "__main__":
    seed()
