__all__ = [
    "CALLER_EXPANSIONHUNTER",
    "CALLER_HIPSTR",
    "CALLER_GANGSTR",
    "CALLER_REPEATHMM",
    "CALLER_STRAGLR",
    "CALLER_TANDEM_GENOTYPES",

    "M_CHROMOSOME_NAMES",
    "X_CHROMOSOME_NAMES",
    "Y_CHROMOSOME_NAMES",
    "SEX_CHROMOSOMES",
    "AUTOSOMES",
    "CHROMOSOMES",

    "MI_CALLERS",
]

CALLER_EXPANSIONHUNTER = "expansionhunter"
CALLER_HIPSTR = "hipstr"
CALLER_LONGTR = "longtr"
CALLER_GANGSTR = "gangstr"
CALLER_GENERIC_VCF = "generic-vcf"
CALLER_REPEATHMM = "repeathmm"
CALLER_STRDUST = "strdust"
CALLER_STRAGLR = "straglr"
CALLER_STRKIT = "strkit"
CALLER_STRKIT_JSON = "strkit-json"
CALLER_STRKIT_VCF = "strkit-vcf"
CALLER_TANDEM_GENOTYPES = "tandem-genotypes"
CALLER_TRGT = "trgt"

M_CHROMOSOME_NAMES = ("chrM", "M")
X_CHROMOSOME_NAMES = ("chrX", "X")
Y_CHROMOSOME_NAMES = ("chrY", "Y")
SEX_CHROMOSOMES = (*X_CHROMOSOME_NAMES, *Y_CHROMOSOME_NAMES)

AUTOSOMES = (
    *map(str, range(1, 23)),
    *(f"chr{i}" for i in range(1, 23)),
)

CHROMOSOMES = (
    *AUTOSOMES,
    *SEX_CHROMOSOMES,
)


MI_CALLERS = (
    CALLER_EXPANSIONHUNTER,
    CALLER_GANGSTR,
    CALLER_GENERIC_VCF,
    CALLER_LONGTR,
    CALLER_REPEATHMM,
    CALLER_STRDUST,
    CALLER_STRAGLR,
    CALLER_STRKIT,
    CALLER_STRKIT_JSON,
    CALLER_STRKIT_VCF,
    CALLER_TANDEM_GENOTYPES,
    CALLER_TRGT,
)
