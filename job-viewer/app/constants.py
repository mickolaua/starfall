"""UI option catalogs shared by upload/submit forms."""

TELESCOPES = (("mondy_azt33ik", "Mondy/AZT-33IK"), ("abao_as32", "AbAO/AS-32"))

OPTICAL_FILTERS = (
    ("clear", "Clear light"),
    ("Rc", "Rc"),
    ("Ic", "Ic"),
    ("Vj", "Vj"),
    ("Bj", "Bj"),
    ("Uj", "Uj"),
    ("u_sloan", "u'"),
    ("g_sloan", "g'"),
    ("r_sloan", "r'"),
    ("i_sloan", "i'"),
    ("z_sloan", "z'"),
)

STACK_MODES = (
    ("none", "No stacking"),
    ("average", "Average"),
    ("median", "Median"),
    ("sum", "Sum"),
)

ASTROMETRIC_CATALOGS = (
    ("usnob", "USNO-B1.0"),
    # ("ps1", "PanSTARRS-DR1"),
    # ("sdss_dr12", "SDSD-DR12"),
    # ("gaia_edr3", "GAIA-EDR3"),
    # ("twomass", "2MASS-PSC"),
)

PHOTOMETRIC_CATALOGS = (
    ("usnob", "USNO-B1.0"),
    # ("ps1", "PanSTARRS-DR1"),
    # ("sdss_dr12", "SDSD-DR12"),
    # ("twomass", "2MASS-PSC"),
    # ("gaia_edr3", "GAIA-EDR3"),
)

PREVIEW_EXTENSIONS = {
    ".bmp",
    ".fit",
    ".fits",
    ".fts",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
TEXT_PREVIEW_EXTENSIONS = {".json", ".log", ".txt", ".proclog"}
STACK_PRODUCT_MARKERS = ("-average", "-median", "-sum")
INPUT_SUBDIRS = ("lights/", "darks/", "flats/", "light/", "dark/", "flat/")
TEXT_PREVIEW_MAX_BYTES = 1_000_000
