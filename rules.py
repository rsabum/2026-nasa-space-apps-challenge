"""Check a rotation against the farmer's ground rules, in plain English.

Owner: Claude-Thomas. Used by app.py (to check the farmer's own rotation and the
suggestion) and by fake_model.py (so the fake suggestion follows the rules too).
The rules themselves are named in contract.CONSTRAINTS.
"""
from contract import CROP_LABELS


def _label(crop):
    return CROP_LABELS.get(crop, str(crop))


def _years(numbers):
    """[2] -> 'year 2', [1, 3] -> 'years 1 and 3'."""
    words = [str(n) for n in numbers]
    if len(words) == 1:
        return f"year {words[0]}"
    return f"years {', '.join(words[:-1])} and {words[-1]}"


def rule_problems(plan, farm, constraints):
    """Return one sentence per broken rule. An empty list means every rule is met.

    plan        {field name: [crop for year 1, year 2, ...]}
    farm        the farm dict (fields with name, acres, last_crop)
    constraints the ground rules, same keys as contract.CONSTRAINTS
    """
    problems = []
    fields = {f["name"]: f for f in farm["fields"]}
    allowed = constraints.get("allowed_crops")
    min_soy = constraints.get("min_legume_years", 0)

    # Two rules that can never both hold: say so once instead of field by field.
    soy_blocked = min_soy > 0 and allowed and "soybeans" not in allowed
    if soy_blocked:
        problems.append("Your soybean rule needs Soybeans on your crop list.")

    # Rules that apply to one field at a time.
    for field, crops in plan.items():
        # 1. Only crops on the farmer's list.
        if allowed:
            for crop in dict.fromkeys(c for c in crops if c not in allowed):
                when = [i + 1 for i, c in enumerate(crops) if c == crop]
                problems.append(f"{field} grows {_label(crop)} in {_years(when)}, "
                                "which isn't on your crop list.")

        # 2. No crop two years running (last season counts against year 1).
        if constraints.get("no_repeat"):
            prev = fields.get(field, {}).get("last_crop")
            for i, crop in enumerate(crops):
                if crop == prev:
                    when = "last season and year 1" if i == 0 else _years([i, i + 1])
                    problems.append(f"{field} has {_label(crop)} two years running ({when}).")
                prev = crop

        # 3. At least N soybean years per field.
        have = crops.count("soybeans")
        if have < min_soy and not soy_blocked:
            if have == 0:
                problems.append(f"{field} has no soybean year.")
            else:
                problems.append(f"{field} has {have} soybean year{'s' if have > 1 else ''}; "
                                f"your rule asks for {min_soy}.")

    # 4. No crop over the acreage cap in any single year.
    cap = constraints.get("max_crop_share", 1)
    total = sum(fields[f]["acres"] for f in plan if f in fields)
    biggest = max((f for f in plan if f in fields), key=lambda f: fields[f]["acres"], default=None)
    if cap < 1 and total > 0 and fields[biggest]["acres"] / total > cap + 1e-9:
        # One field alone is over the cap, so whatever grows there breaks it.
        problems.append(f"Your biggest field, {biggest}, is {fields[biggest]['acres'] / total:.0%} "
                        f"of your acres, so no plan can keep every crop under {cap:.0%}. "
                        "Raise “Most acres in one crop”.")
    elif cap < 1 and total > 0:
        n_years = max((len(c) for c in plan.values()), default=0)
        for i in range(n_years):
            acres = {}
            for field, crops in plan.items():
                if i < len(crops) and field in fields:
                    acres[crops[i]] = acres.get(crops[i], 0) + fields[field]["acres"]
            for crop, a in acres.items():
                if a / total > cap + 1e-9:
                    problems.append(f"In year {i + 1}, {_label(crop)} covers {a / total:.0%} "
                                    f"of your acres (your limit is {cap:.0%}).")
    return problems
