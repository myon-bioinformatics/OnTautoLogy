"""Explicit English marker slots for observed arguments and annotations."""
import ontautology as ot

# A working inventory. Add corpus-specific expressions verbatim, including multiword markers.
MARKERS = tuple("""@none aboard about above absent across after against along alongside amid amidst among amongst
around as astride at atop bar barring before behind below beneath beside besides between beyond but by circa
concerning considering despite down during except excepting excluding following for from given in including
inside into like minus near notwithstanding of off on onto opposite out outside over past pending per plus
regarding round save since than through throughout till to toward towards under underneath unlike until up upon
versus via with within without""".split()) + (
    "according to", "ahead of", "apart from", "as for", "as of", "as per", "as to", "because of",
    "by means of", "due to", "except for", "far from", "hereafter in", "in accordance with", "in addition to",
    "in case of", "in front of", "in lieu of", "in relation to", "in spite of", "instead of",
    "next to", "on account of", "on behalf of", "on top of", "out of", "owing to", "prior to",
    "pursuant to", "rather than", "regardless of", "subject to", "together with", "with respect to",
)


def marker_slots(entries, profile=MARKERS):
    """Null slot = unreported. A named role with a null value = explicitly unknown filler."""
    if not isinstance(entries, dict):
        raise ValueError("markers must be an object")
    slots = dict.fromkeys(profile)
    meanings = {}
    for marker, arguments in entries.items():
        ot._nonempty_str(marker, "marker")
        if arguments is not None:
            if not isinstance(arguments, list):
                raise ValueError(f"{marker}: provide null or a list of arguments")
            for arg in arguments:
                if (not isinstance(arg, dict) or not {"role", "value"} <= arg.keys()
                        or arg.keys() - {"role", "value", "expression", "meaning"}):
                    raise ValueError(f"{marker}: each argument needs role and value")
                ot._nonempty_str(arg["role"], "role")
                value = arg["value"]
                if value is not None:
                    ot._nonempty_str(value, "value")
                if "expression" in arg:
                    ot._nonempty_str(arg["expression"], "expression")
                if "meaning" in arg:
                    key = ot._nonempty_str(arg["meaning"], "meaning")
                    interpretation = (arg["role"], value)
                    if meanings.setdefault(key, interpretation) != interpretation:
                        raise ValueError(f"{marker}: meaning {key!r} has conflicting roles or values")
        slots[marker] = arguments
    return slots
