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
    # Symbol    name_ar                                              name_en                                   Sector                   Sharia
    # ── البنوك ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("COMI",   "البنك التجاري الدولي",                             "Commercial International Bank",           "البنوك",                False),
    ("CIEB",   "بنك كريدي أجريكول مصر",                           "Credit Agricole Egypt",                   "البنوك",                False),
    ("QNBE",   "بنك قطر الوطني الأهلي",                           "QNB Alahli",                              "البنوك",                False),
    ("ADIB",   "مصرف أبوظبي الإسلامي - مصر",                     "Abu Dhabi Islamic Bank Egypt",            "البنوك",                True),
    ("SAUD",   "بنك البركة مصر",                                   "Al Baraka Bank Egypt",                    "البنوك",                True),
    ("FAIT",   "بنك فيصل الإسلامي المصري - بالجنيه",              "Faisal Islamic Bank - EGP",               "البنوك",                True),
    ("FAITA",  "بنك فيصل الإسلامي المصري - بالدولار",             "Faisal Islamic Bank - USD",               "البنوك",                True),
    ("NBKE",   "بنك الكويت الوطني - مصر",                         "National Bank of Kuwait Egypt",           "البنوك",                False),
    ("CANA",   "بنك قناة السويس",                                  "Canal Bank",                              "البنوك",                False),
    ("HDBK",   "بنك التعمير والإسكان",                            "Housing & Development Bank",              "البنوك",                False),
    ("EGBE",   "بنك الخليج المصري",                                "Egyptian Gulf Bank",                      "البنوك",                False),
    ("EXPA",   "البنك المصري لتنمية الصادرات",                    "Export Development Bank of Egypt",        "البنوك",                False),
    ("SAIB",   "الشركة المصرفية العربية الدولية",                 "SAIB Bank",                               "البنوك",                False),
    ("UBEE",   "المصرف المتحد",                                    "United Bank of Egypt",                    "البنوك",                False),
    ("ARCC",   "العربية للإسمنت",                                  "Arab Cement",                             "مواد البناء",           False),
    # ── العقارات ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("TMGH",   "مجموعة طلعت مصطفى القابضة",                      "Talaat Moustafa Group",                   "العقارات",              False),
    ("MASR",   "مدينة مصر للإسكان والتعمير",                     "Madinet Masr",                            "العقارات",              False),
    ("PHDC",   "بالم هيلز للتعمير",                               "Palm Hills Developments",                 "العقارات",              False),
    ("MNHD",   "مدينة نصر للإسكان والتعمير",                     "Madinet Nasr Housing",                    "العقارات",              False),
    ("OCDI",   "السادس من أكتوبر للتنمية والاستثمار (سوديك)",    "SODIC",                                   "العقارات",              False),
    ("ORHD",   "أوراسكوم للتنمية مصر",                           "Orascom Development Egypt",               "العقارات",              False),
    ("RREI",   "الاستثمار العقاري العربي - إليكو",               "RREI",                                    "العقارات",              False),
    ("HELI",   "مصر الجديدة للإسكان والتعمير",                   "Heliopolis Housing",                      "العقارات",              False),
    ("EMFD",   "إعمار مصر للتنمية",                               "EMAAR Misr",                              "العقارات",              False),
    ("UTOP",   "يوتوبيا للاستثمار العقاري والسياحي",             "Utopia Real Estate Investment",           "العقارات",              False),
    ("PRDC",   "بايونيرز بروبرتيز للتنمية العمرانية",            "Pioneers Properties",                     "العقارات",              False),
    ("TANM",   "تنمية للاستثمار العقاري",                         "Tanmeyah Real Estate",                    "العقارات",              False),
    ("CIRA",   "القاهرة للاستثمار والتنمية العقارية",             "CIRA",                                    "العقارات",              False),
    ("IDRE",   "الاسماعيلية الجديدة للتطوير والتعمير",           "Ismailia New Development",                "العقارات",              False),
    ("EHDR",   "المصريين للإسكان والتنمية والتعمير",              "Egyptians Housing Development",           "العقارات",              False),
    ("ELKA",   "القاهرة للإسكان والتعمير",                       "Cairo Housing & Development",             "العقارات",              False),
    ("ELSH",   "الشمس للإسكان والتعمير",                         "Al Shams Housing",                        "العقارات",              False),
    ("UNIT",   "المتحدة للإسكان والتعمير",                       "United Housing & Development",            "العقارات",              False),
    ("NHPS",   "الوطنية للإسكان للنقابات المهنية",               "National Housing for Professionals",      "العقارات",              False),
    ("ZMID",   "زهراء المعادي للاستثمار والتعمير",               "Zahraa Al Maadi Investment",              "العقارات",              False),
    ("ADRI",   "العربية للتنمية والاستثمار العقاري",              "Arab for Real Estate Investment",         "العقارات",              False),
    ("CCRS",   "الخليجية الكندية للاستثمار العقاري",              "Gulf Canadian for Real Estate",           "العقارات",              False),
    ("MENA",   "مينا للاستثمار السياحي والعقاري",                "MENA Tourism & Real Estate",              "العقارات",              False),
    ("GPIM",   "جي بي آي للنمو العمراني",                         "GPI for Urban Growth",                    "العقارات",              False),
    ("NARE",   "مجموعة النعيم العقارية القابضة",                  "Al Naeem Real Estate Group",              "العقارات",              False),
    ("AREH",   "المجموعة المصرية العقارية",                       "Egyptian Real Estate Group",              "العقارات",              False),
    ("COPR",   "كوبر للاستثمار التجاري والتطوير العقاري",        "Cooper Real Estate",                      "العقارات",              False),
    ("CFGH",   "كونكريت فاشون جروب للاستثمار",                   "Concrete Fashion Group",                  "العقارات",              False),
    ("FIRE",   "الأولى للاستثمار والتنمية العقارية",              "First Real Estate Investment",            "العقارات",              False),
    ("ARAB",   "المطورون العرب القابضة",                           "Arab Developers Holding",                 "العقارات",              False),
    ("GIHD",   "الغربية الإسلامية للتنمية العمرانية",             "Gharbia Islamic Housing",                 "العقارات",              True),
    # ── الأدوية والرعاية الصحية ───────────────────────────────────────────────────────────────────────────────────────────────────────
    ("ISPH",   "ابن سينا فارما",                                   "Ibn Sina Pharma",                         "الأدوية",               False),
    ("OCPH",   "أكتوبر فارما",                                     "October Pharma",                          "الأدوية",               False),
    ("BIOC",   "جلاكسو سميث كلاين مصر",                           "GSK Egypt",                               "الأدوية",               False),
    ("PHAR",   "المصرية الدولية للصناعات الدوائية - إيبيكو",      "EIPICO",                                  "الأدوية",               False),
    ("NIPH",   "النيل للأدوية والصناعات الكيماوية",               "Nile Pharmaceutical",                     "الأدوية",               False),
    ("MIPH",   "مينا فارم للأدوية والصناعات الكيماوية",           "Mina Pharm",                              "الأدوية",               False),
    ("SIPC",   "سبأ الدولية للأدوية والصناعات الكيماوية",         "Siba International Pharma",               "الأدوية",               False),
    ("MPCI",   "ممفيس للأدوية والصناعات الكيماوية",               "Memphis Pharmaceutical",                  "الأدوية",               False),
    ("RMDA",   "العاشر من رمضان للصناعات الدوائية",               "10th of Ramadan Pharmaceutical",         "الأدوية",               False),
    ("AXPH",   "الإسكندرية للأدوية والصناعات الكيماوية",          "Alexandria Pharmaceutical",               "الأدوية",               False),
    ("UPMS",   "الاتحاد الصيدلي للخدمات الطبية",                 "UPMS",                                    "الأدوية",               False),
    ("ADCI",   "العربية للأدوية والصناعات الكيماوية",             "Arab Drug Industries",                    "الأدوية",               False),
    ("CLHO",   "شركة مستشفيات كليوباترا",                          "Cleopatra Hospitals",                     "الرعاية الصحية",        False),
    ("NINH",   "مستشفى النزهة الدولي",                             "Nozha International Hospital",            "الرعاية الصحية",        False),
    ("AMES",   "الإسكندرية للخدمات الطبية",                       "Alexandria Medical Services",             "الرعاية الصحية",        False),
    ("PHGC",   "بريميم هيلث كير جروب",                            "Premium Healthcare Group",                "الرعاية الصحية",        False),
    ("FCMD",   "فيوتشر كير للصناعات الطبية",                      "Future Care Medical",                     "الرعاية الصحية",        False),
    # ── البتروكيماويات والطاقة ────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("AMOC",   "الإسكندرية للزيوت المعدنية",                      "Alexandria Mineral Oils Company",         "البتروكيماويات",        False),
    ("SKPC",   "سيدي كرير للبتروكيماويات",                        "Sidi Kerir Petrochemicals",               "البتروكيماويات",        True),
    ("EGAS",   "غاز مصر - إيجاس",                                  "Egypt Gas",                               "الطاقة",                False),
    ("ABUK",   "أبوقير للأسمدة والصناعات الكيماوية",              "Abu Qir Fertilizers",                     "الصناعات الكيماوية",    True),
    ("KIMA",   "كيما - أسوان للأسمدة",                            "Kima",                                    "الصناعات الكيماوية",    False),
    ("TAQA",   "طاقة عربية",                                       "Arab Taqa",                               "الطاقة",                False),
    ("KORA",   "قرة لمشروعات الطاقة والاستثمار",                  "Korra Energy",                            "الطاقة",                False),
    # ── الغذاء والشراب ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("JUFO",   "جهينة للصناعات الغذائية",                         "Juhayna Food Industries",                 "الغذاء والشراب",        True),
    ("POUL",   "القاهرة للدواجن",                                  "Cairo Poultry",                           "الغذاء والشراب",        True),
    ("DOMT",   "الصناعات الغذائية العربية - دومتي",               "Domty",                                   "الغذاء والشراب",        False),
    ("AJWA",   "اجواء للصناعات الغذائية - مصر",                   "Ajwa Food Industries",                    "الغذاء والشراب",        True),
    ("EFID",   "ايديتا للصناعات الغذائية",                        "Edita Food Industries",                   "الغذاء والشراب",        False),
    ("EAST",   "الشرقية - إيسترن كومباني",                        "Eastern Company",                         "الغذاء والشراب",        False),
    ("OLFI",   "عبور لاند للصناعات الغذائية",                     "Obuorland Food",                          "الغذاء والشراب",        False),
    ("ISMA",   "الاسماعيلية مصر للدواجن",                         "Ismailia Misr Poultry",                   "الغذاء والشراب",        True),
    ("EPCO",   "المصرية للدواجن",                                  "Egyptian Poultry",                        "الغذاء والشراب",        True),
    ("MPCO",   "المنصورة للدواجن",                                 "Mansoura Poultry",                        "الغذاء والشراب",        True),
    ("SNFI",   "سوهاج الوطنية للصناعات الغذائية",                 "Sohag National Food",                     "الغذاء والشراب",        True),
    ("SNFC",   "الشرقية الوطنية للأمن الغذائي",                   "Eastern National Food Security",          "الغذاء والشراب",        True),
    ("GOUR",   "جورميه إيجيبت للأغذية",                           "Gourmet Egypt",                           "الغذاء والشراب",        False),
    ("SUGR",   "الدلتا للسكر",                                     "Delta Sugar",                             "الغذاء والشراب",        False),
    ("ELNA",   "النصر لتصنيع الحاصلات الزراعية",                  "El Nasr for Agricultural Products",       "الغذاء والشراب",        False),
    ("INFI",   "فوديكو - الاسماعيلية الوطنية للغذاء",             "Foodico",                                 "الغذاء والشراب",        False),
    ("ADPC",   "آراب ديري",                                        "Arab Dairy",                              "الغذاء والشراب",        False),
    ("AIFI",   "اطلس للاستثمار والصناعات الغذائية",               "Atlas Investment & Food Industries",      "الغذاء والشراب",        False),
    # ── مطاحن ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("SCFM",   "مطاحن ومخابز جنوب القاهرة والجيزة",              "South Cairo Flour Mills",                 "الغذاء والشراب",        False),
    ("MILS",   "مطاحن ومخابز شمال القاهرة",                       "North Cairo Flour Mills",                 "الغذاء والشراب",        False),
    ("AFMC",   "مطاحن ومخابز الإسكندرية",                         "Alexandria Flour Mills",                  "الغذاء والشراب",        False),
    ("CEFM",   "مطاحن مصر الوسطى",                                "Middle Egypt Flour Mills",                "الغذاء والشراب",        False),
    ("EDFM",   "مطاحن شرق الدلتا",                                "East Delta Flour Mills",                  "الغذاء والشراب",        False),
    ("ZMID2",  "مطاحن وسط وغرب الدلتا",                           "Middle & West Delta Flour Mills",         "الغذاء والشراب",        False),
    # ── الاتصالات والتكنولوجيا ────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("ETEL",   "المصرية للاتصالات",                                "Telecom Egypt",                           "الاتصالات",             False),
    ("EFIH",   "إى فاينانس للاستثمارات المالية والرقمية",          "e-Finance",                               "التكنولوجيا",           False),
    ("FWRY",   "فوري للتكنولوجيا والمدفوعات الإلكترونية",          "Fawry",                                   "التكنولوجيا",           False),
    ("GTHE",   "جلوبال تيلكوم القابضة",                            "Global Telecom Holding",                  "الاتصالات",             False),
    ("VALU",   "فاليو للتمويل الاستهلاكي",                         "valU Consumer Finance",                   "التكنولوجيا المالية",   False),
    ("DGTZ",   "ديجيتايز للاستثمار والتقنية",                      "Digitize",                                "التكنولوجيا",           False),
    ("SCTS",   "قناة السويس لتوطين التكنولوجيا",                   "Suez Canal Technology Settling",          "التكنولوجيا",           False),
    ("EGSA",   "المصرية للأقمار الصناعية - نايلسات",               "Nilesat",                                 "الاتصالات",             False),
    ("ESAC",   "مصر جنوب أفريقيا للاتصالات",                      "Egypt South Africa Telecom",              "الاتصالات",             False),
    ("ETRS",   "المصرية لخدمات النقل والتجارة الدولية",            "ETRS",                                    "النقل والخدمات",        False),
    # ── الصناعات الأساسية (حديد وألومنيوم) ──────────────────────────────────────────────────────────────────────────────────────────
    ("IRON",   "الحديد والصلب المصرية",                            "Egyptian Iron & Steel",                   "الصناعات الأساسية",     False),
    ("IRAX",   "العز الدخيلة للصلب",                               "Al Ezz Al Dekheila Steel",                "الصناعات الأساسية",     False),
    ("ESRS",   "حديد عز",                                          "Ezz Steel",                               "الصناعات الأساسية",     False),
    ("ATQA",   "مصر الوطنية للصلب - عتاقة",                       "Egyptian National Steel - Atqa",          "الصناعات الأساسية",     False),
    ("EGAL",   "مصر للألومنيوم",                                   "Egyptian Aluminum",                       "الصناعات الأساسية",     False),
    ("ALUM",   "العربية للألومنيوم",                               "Arab Aluminum",                           "الصناعات الأساسية",     False),
    ("ISMQ",   "الحديد والصلب للمناجم والمحاجر",                   "Steel for Mining & Quarries",             "التعدين",               False),
    ("ASCM",   "أسيك للجيولوجيا والتعدين",                        "ASCOM Geology & Mining",                  "التعدين",               False),
    # ── مواد البناء والإسمنت ──────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("SUCE",   "أسمنت السويس",                                     "Suez Cement",                             "مواد البناء",           False),
    ("SCEM",   "أسمنت سيناء",                                      "Sinai Cement",                            "مواد البناء",           False),
    ("TORA",   "الأسمنت والتشييد المصرية - طرة",                  "Tourah Portland Cement",                  "مواد البناء",           False),
    ("SVCE",   "جنوب الوادي للإسمنت",                              "South Valley Cement",                     "مواد البناء",           False),
    ("MCQE",   "مصر للإسمنت - قنا",                               "Misr Cement Qena",                        "مواد البناء",           False),
    ("ALEX",   "الإسكندرية للإسمنت بورتلاند",                     "Alexandria Portland Cement",              "مواد البناء",           False),
    ("MBSC",   "مصر بني سويف للإسمنت",                            "Misr Beni Suef Cement",                   "مواد البناء",           False),
    ("PRCL",   "الشركة العامة لمنتجات السيراميك",                  "Precal Ceramics",                         "مواد البناء",           False),
    ("CERA",   "الخزف العربي - سيراميكا ريماس",                   "Ceramica Remas",                          "مواد البناء",           False),
    ("LCSW",   "ليسيكو مصر",                                       "Lecico Egypt",                            "مواد البناء",           False),
    ("ECAP",   "العز للسيراميك والبورسلين",                        "EZ Ceramics & Porcelain",                 "مواد البناء",           False),
    ("ISGC",   "الإسكندرية للزجاج والكريستال",                    "International Glass & Crystal",           "مواد البناء",           False),
    ("MEGM",   "الشرق الأوسط لصناعة الزجاج",                      "Middle East Glass",                       "مواد البناء",           False),
    # ── الصناعات الكيماوية ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("EGCH",   "الصناعات الكيماوية المصرية",                       "Egyptian Chemical Industries",            "الصناعات الكيماوية",    False),
    ("MICH",   "مصر لصناعة الكيماويات",                            "Misr Chemical Industries",                "الصناعات الكيماوية",    False),
    ("ICFC",   "الدولية للأسمدة والكيماويات",                      "International Co. for Fertilizers",       "الصناعات الكيماوية",    False),
    ("KZPC",   "قفر الزيات للمبيدات والكيماويات",                 "Kafr El Zayat Pesticides",                "الصناعات الكيماوية",    False),
    ("MFPC",   "مصر لإنتاج الأسمدة - موبكو",                      "MOPCO",                                   "الصناعات الكيماوية",    True),
    ("PACH",   "البويات والصناعات الكيماوية - باكين",              "Paints & Chemical Industries",            "الصناعات الكيماوية",    False),
    ("MOSC",   "مصر للزيوت والصابون",                              "Misr for Oils & Soap",                    "الصناعات الكيماوية",    False),
    ("COSG",   "القاهرة للزيوت والصابون",                          "Cairo Oils & Soap",                       "الصناعات الكيماوية",    False),
    ("DIFC",   "الدولية للثلج الجاف - ديفكو",                     "DIFCO",                                   "الصناعات الكيماوية",    False),
    ("ZEOT",   "الزيوت المستخلصة ومنتجاتها",                      "Extracted Oils & Products",               "الصناعات الكيماوية",    False),
    ("SMFR",   "سماد مصر - إيجيفرت",                              "Egypt Fertilizers - Egifert",             "الصناعات الكيماوية",    False),
    # ── الصناعات الهندسية ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("SWDY",   "السويدي إليكتريك",                                 "El Sewedy Electric",                      "الصناعات الهندسية",     False),
    ("ELEC",   "الكابلات الكهربائية المصرية",                      "Egyptian Electrical Cables",              "الصناعات الهندسية",     False),
    ("ENGC",   "الصناعات الهندسية المعمارية والإنشائية",           "Engineering & Construction Industries",   "الصناعات الهندسية",     False),
    ("EEII",   "العربية للصناعات الهندسية",                        "Arab Engineering Industries",             "الصناعات الهندسية",     False),
    ("ARVA",   "العربية للمحابس",                                   "Arabian Valves",                          "الصناعات الهندسية",     False),
    ("IEEC",   "المشروعات الصناعية والهندسية",                     "Industrial & Engineering Projects",       "الصناعات الهندسية",     False),
    ("INEG",   "المجموعة المتكاملة للأعمال الهندسية",              "Integrated Engineering Group",            "الصناعات الهندسية",     False),
    ("MTIE",   "إمام جروب للصناعة والتجارة العالمية",              "Imam Group for Industry & Trade",         "الصناعات الهندسية",     False),
    ("RUBX",   "روبكس العالمية لتصنيع البلاستيك",                 "Rubex International Plastic",             "الصناعات الهندسية",     False),
    ("VERT",   "فيرتيكا للصناعة والتجارة",                        "Vertica",                                 "الصناعات الهندسية",     False),
    ("MBEG",   "أم بي للهندسة",                                    "MB Engineering",                          "الصناعات الهندسية",     False),
    # ── الصناعات النسيجية ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("ORWE",   "النساجون الشرقيون للسجاد",                         "Oriental Weavers",                        "الصناعات النسيجية",     False),
    ("SPIN",   "الإسكندرية للغزل والنسيج",                        "Alexandria Spinning & Weaving",           "الصناعات النسيجية",     False),
    ("ACGC",   "العربية لحليج الأقطان",                            "Arab Cotton Ginning",                     "الصناعات النسيجية",     False),
    ("APSW",   "العربية وبولفارا للغزل والنسيج",                  "Arab & Polyfara for Spinning",            "الصناعات النسيجية",     False),
    ("KABO",   "النصر للملابس والمنسوجات - كابو",                 "Kabo Textiles",                           "الصناعات النسيجية",     False),
    ("NCGC",   "النيل لحليج الأقطان",                              "Nile Cotton Ginning",                     "الصناعات النسيجية",     False),
    ("DSCW",   "دايس للملابس الجاهزة",                             "DICE Ready Wear",                         "الصناعات النسيجية",     False),
    ("GTWL",   "جولدن تكس للأصواف",                               "Golden Tex Wool",                         "الصناعات النسيجية",     False),
    # ── التشييد والبناء ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("ORAS",   "أوراسكوم للإنشاء",                                 "Orascom Construction",                    "التشييد والبناء",       False),
    ("OBRI",   "أوراسكوم للإنشاء والصناعة",                       "Orascom Building Materials",              "التشييد والبناء",       False),
    ("ACRO",   "أكرو مصر للشدات والسقالات",                       "Acrow Egypt",                             "التشييد والبناء",       False),
    ("NCCW",   "النصر للأعمال المدنية",                            "Nasr City for Civil Works",               "التشييد والبناء",       False),
    ("GGCC",   "الجيزة العامة للمقاولات والاستثمار",               "Giza General Contracting",                "التشييد والبناء",       False),
    ("CRST",   "كريستمارك للمقاولات والتطوير العقاري",            "Crystalmark Contracting",                 "التشييد والبناء",       False),
    ("FNAR",   "الفنار للمقاولات العمومية والإنشائية",             "El Fnar for Public Contracting",          "التشييد والبناء",       False),
    ("DAPH",   "التعمير والاستشارات الهندسية",                     "Taameir Engineering",                     "التشييد والبناء",       False),
    ("DCRC",   "دلتا للإنشاء والتعمير",                            "Delta Construction",                      "التشييد والبناء",       False),
    ("UEGC",   "الصعيد العامة للمقاولات والاستثمار",               "Upper Egypt Contractors",                 "التشييد والبناء",       False),
    # ── المالية والاستثمار ────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("HRHO",   "مجموعة أي إف جي القابضة",                          "EFG Hermes Holding",                      "المالية",               False),
    ("EFIH",   "إى فاينانس للاستثمارات المالية والرقمية",          "e-Finance for Financial & Digital Inv.",  "المالية",               False),
    ("BTFH",   "بلتون المالية القابضة",                             "Beltone Financial Holding",               "المالية",               False),
    ("CCAP",   "القلعة للاستشارات المالية",                         "Al Qalaa Financial",                      "المالية",               False),
    ("HCFI",   "القابضة للاستثمارات المالية",                       "HC Securities & Investment",              "المالية",               False),
    ("CNFN",   "كونتكت المالية القابضة",                            "Contact Financial Holding",               "المالية",               False),
    ("CICH",   "سي آي كابيتال القابضة للاستثمار",                  "CI Capital Holding",                      "المالية",               False),
    ("PRMH",   "برايم القابضة للاستثمارات المالية",                "Prime Holding",                           "المالية",               False),
    ("RKAZ",   "ركاز القابضة للاستثمارات المالية",                 "Rekaz Financial Investments Holding",     "المالية",               False),
    ("ATLC",   "التوفيق للتأجير التمويلي",                         "Al Tawfik Leasing",                       "المالية",               False),
    ("ICLE",   "الدولية للتأجير التمويلي - إنكوليس",               "Incolease",                               "المالية",               False),
    ("TWSA",   "توسع للتخصيم",                                      "Tawsea Factoring",                        "المالية",               False),
    ("EFIC",   "المالية والصناعية المصرية",                         "Egyptian Financial & Industrial",         "المالية",               False),
    ("CPME",   "كاتليست بارتنرز",                                   "Catalyst Partners",                       "المالية",               False),
    ("OFH",    "أو بي المالية القابضة",                             "OB Financial Holding",                    "المالية",               False),
    ("ODIN",   "أودن للاستثمارات المالية",                          "Odin Financial Investments",              "المالية",               False),
    ("KWIN",   "القاهرة الوطنية للاستثمار والأوراق المالية",        "Cairo National Securities",               "المالية",               False),
    ("EASB",   "المصرية العربية لتداول الأوراق المالية",            "Egyptian Arab Securities",                "المالية",               False),
    ("EBSC",   "أصول للوساطة في الأوراق المالية",                  "Osuol Securities Brokerage",              "المالية",               False),
    ("EOSB",   "العروبة للسمسرة في الأوراق المالية",                "Arouba Securities",                       "المالية",               False),
    ("MOIN",   "المهندس للتأمين",                                   "Engineers Misr Insurance",                "التأمين",               False),
    ("DEIN",   "الدلتا للتأمين",                                    "Delta Insurance",                         "التأمين",               False),
    ("RACC",   "راية لخدمات مراكز الاتصالات",                      "Raya Contact Center",                     "التكنولوجيا",           False),
    ("RAYA",   "راية القابضة للاستثمارات المالية",                 "Raya Holding",                            "الاستثمار",             False),
    ("GBCO",   "جي بي كورب",                                        "GB Corp",                                 "الاستثمار",             False),
    ("GCFI",   "جراند انفستمنت القابضة",                            "Grand Investment Holding",                "الاستثمار",             False),
    ("OIH",    "أوراسكوم للاستثمار القابضة",                        "Orascom Investment Holding",              "الاستثمار",             False),
    ("MKIT",   "المصرية الكويتية للاستثمار والتجارة",               "Egyptian Kuwaiti Holding",                "الاستثمار",             False),
    ("NAHO",   "النعيم القابضة للاستثمارات",                        "Al Naeem Holding",                        "الاستثمار",             False),
    ("BIDI",   "البدر للاستثمار والتنمية",                          "Badr Investment",                         "الاستثمار",             False),
    ("BIGP",   "بي آي جي للتجارة والاستثمار",                      "BIG for Commerce & Investment",           "الاستثمار",             False),
    ("HBCO",   "هيبكو للاستثمارات التجارية والتنمية",               "HEBCO",                                   "الاستثمار",             False),
    ("IBCT",   "إنترناشيونال بيزنس كوربوريشن",                     "International Business Corporation",      "الاستثمار",             False),
    ("ELWA",   "الوادي العالمية للاستثمار والتنمية",                "El Wadi International",                   "الاستثمار",             False),
    ("AIDC",   "العربية للاستثمار والتطوير",                        "Arab Investment & Development",           "الاستثمار",             False),
    ("AMIA",   "الملتقى العربي للاستثمار",                          "Arab Meeting for Investment",             "الاستثمار",             False),
    ("GDWA",   "جدوى للتنمية الصناعية",                             "Jadwa Industrial Development",            "الاستثمار",             False),
    ("GMCI",   "مجموعة جي.أم.سي للاستثمارات",                     "GMC Group",                               "الاستثمار",             False),
    ("GTEX",   "جيتكس للاستثمارات التجارية والعقارية",              "Getex Investments",                       "الاستثمار",             False),
    ("ICID",   "العالمية للاستثمار والتنمية",                       "International for Investment & Dev.",     "الاستثمار",             False),
    ("TYCN",   "تايكون إنفستمنتس هولدينج",                         "Tycoon Investments Holding",              "الاستثمار",             False),
    ("SEIG",   "السعودية المصرية للاستثمار والتمويل",               "Saudi Egyptian Investment",               "الاستثمار",             False),
    ("ACAMD",  "الشركة العربية لإدارة وتطوير الأصول",               "Arab Assets Management & Development",    "الاستثمار",             False),
    ("AMPI",   "نوفيدا للاستثمار والتكنولوجيا",                    "Novida Investment & Technology",          "الاستثمار",             False),
    # ── الزراعة ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("AALR",   "العامة لاستصلاح الأراضي والتنمية الزراعية",        "General Company for Land Reclamation",    "الزراعة",               False),
    ("EALR",   "العربية لاستصلاح الأراضي",                          "Arabian Agricultural Services",           "الزراعة",               False),
    ("IFAP",   "الدولية للمحاصيل الزراعية",                         "International Agricultural Products",     "الزراعة",               False),
    ("NEDA",   "شمال الصعيد للتنمية والإنتاج الزراعي",              "North Sohag Development",                 "الزراعة",               False),
    ("KRDI",   "نهر الخير للتنمية والاستثمار الزراعي",              "Nahr El Khair Agricultural",              "الزراعة",               True),
    ("LUTS",   "لوتس للتنمية والاستثمار الزراعي",                   "Lotus Agricultural",                      "الزراعة",               False),
    ("GGRN",   "جو جرين للاستثمار الزراعي والتنمية",               "Go Green Agricultural Investment",        "الزراعة",               True),
    ("WCDF",   "وادي كوم أمبو لاستصلاح الأراضي",                  "Wadi Kom Ombo",                           "الزراعة",               False),
    # ── التجزئة ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("MCRO",   "ماكرو جروب",                                        "Macro Group Pharmaceuticals",             "التجزئة",               False),
    ("MFSC",   "مصر للأسواق الحرة",                                 "Egypt Free Shops",                        "التجزئة",               False),
    # ── السياحة والترفيه ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("AMER",   "مجموعة عامر القابضة",                               "Amer Group Holding",                      "السياحة والترفيه",      False),
    ("MMAT",   "مرسى علم للتنمية السياحية",                         "Marsa Alam Tourism Development",          "السياحة والترفيه",      False),
    ("MHOT",   "مصر للفنادق",                                       "Misr Hotels",                             "السياحة والترفيه",      False),
    ("EGTS",   "المصرية للمنتجعات السياحية",                        "Egyptian Tourism Resorts",                "السياحة والترفيه",      False),
    ("SDTI",   "شارم دريمز للاستثمار السياحي",                     "Sharm Dreams Tourism Investment",         "السياحة والترفيه",      False),
    ("SPHT",   "الشمس بيراميدز للفنادق والمنشآت السياحية",         "Al Shams Pyramids Hotels",                "السياحة والترفيه",      False),
    ("PHTV",   "بيراميزا للفنادق والقرى السياحية",                  "Pyramisa Hotels",                         "السياحة والترفيه",      False),
    ("RMTV",   "رواد مصر للاستثمار السياحي",                       "Rowad Masr Tourism",                      "السياحة والترفيه",      False),
    ("ROTO",   "رواد السياحة",                                       "Rowad El Seyaha",                         "السياحة والترفيه",      False),
    ("RTVC",   "رمكو لإنشاء القرى السياحية",                        "REMCO",                                   "السياحة والترفيه",      False),
    ("GPPL",   "جولدن بيراميدز بلازا",                              "Golden Pyramids Plaza",                   "السياحة والترفيه",      False),
    ("GOCO",   "جولدن كوست السخنة للاستثمار",                      "Golden Coast Ain Sokhna",                 "السياحة والترفيه",      False),
    ("FTNS",   "فتنس برايم للأندية الصحية",                        "Fitness Prime",                           "السياحة والترفيه",      False),
    ("MAAL",   "مرسيليا المصرية الخليجية للاستثمار",               "Marseilia Egypt Gulf",                    "السياحة والترفيه",      False),
    ("TRTO",   "عبر المحيطات للسياحة",                              "Trans-Oceans Tourism",                    "السياحة والترفيه",      False),
    ("EITP",   "المصرية للمشروعات السياحية",                        "Egyptian Tourism Projects",               "السياحة والترفيه",      False),
    ("MPRC",   "المصرية لمدينة الإنتاج الإعلامي",                   "EMPC - Media Production City",            "الترفيه والإعلام",      False),
    # ── التعليم ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("CAED",   "القاهرة للخدمات التعليمية",                         "Cairo Education Services",                "التعليم",               False),
    ("MOED",   "المصرية لنظم التعليم الحديثة",                      "Modern Education Systems",                "التعليم",               False),
    ("TALM",   "تعليم لخدمات الإدارة",                              "Taaleem Management Services",             "التعليم",               False),
    # ── النقل والخدمات ────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("ALCN",   "الإسكندرية لتداول الحاويات والبضائع",               "Alexandria Container & Cargo",            "النقل والخدمات",        False),
    ("UASG",   "العربية المتحدة للشحن والتفريغ",                    "United Arab Shipping",                    "النقل والخدمات",        False),
    ("MOIL",   "الخدمات الملاحية والبترولية - ماريدية",             "Maritime & Petroleum Services",           "النقل والخدمات",        False),
    ("CSAG",   "القناة للتوكيلات الملاحية",                         "Canal Shipping Agencies",                 "النقل والخدمات",        False),
    ("GSSC",   "العامة للصوامع والتخزين",                           "General Silos & Storage",                 "النقل والخدمات",        False),
    # ── الصناعات الورقية والطباعة ─────────────────────────────────────────────────────────────────────────────────────────────────────
    ("DTPP",   "دلتا للطباعة والتغليف",                             "Delta for Printing & Packaging",          "الصناعات الأساسية",     False),
    ("EPPK",   "الأهرام للطباعة والتغليف",                          "Al Ahram Beverage Packaging",             "الصناعات الأساسية",     False),
    ("SMPP",   "الشروق الحديثة للطباعة والتغليف",                  "Shorouk Modern Printing",                 "الصناعات الأساسية",     False),
    ("NAPR",   "الوطنية للطباعة",                                   "National Printing",                       "الصناعات الأساسية",     False),
    ("RAKT",   "الشركة العامة لصناعة الورق",                        "General Paper Industry",                  "الصناعات الأساسية",     False),
    ("SIMO",   "الورق للشرق الأوسط - سيمو",                         "SIMO Paper",                              "الصناعات الأساسية",     False),
    # ── متنوع ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    ("APPC",   "العبوات الدوائية المتطورة",                         "Advanced Pharmaceutical Packaging",       "الصناعات الأساسية",     False),
    ("MEPA",   "العبوات الطبية",                                    "Medical Packaging",                       "الصناعات الأساسية",     False),
    ("UNIP",   "يونيفرسال لصناعة مواد التعبئة",                    "Universal for Packaging",                 "الصناعات الأساسية",     False),
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
                changed = (
                    existing.name_ar != name_ar
                    or existing.name_en != name_en
                    or existing.sector != sector
                    or existing.is_sharia != is_sharia
                )
                if changed:
                    existing.name_ar   = name_ar
                    existing.name_en   = name_en
                    existing.sector    = sector
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
        print(f"Seed complete: {added} added, {updated} updated, {skipped} unchanged.")


if __name__ == "__main__":
    seed()
