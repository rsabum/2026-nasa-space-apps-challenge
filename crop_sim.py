"""Stage 1 crop model: a daily soil-water bucket plus the FAO-33 yield formula (owner: Robert).

The bucket restarts every season, so a crop's water result depends only on
(soil, crop, rye cover the winter before, irrigated or not, weather year). That's a small
table, computed once and reused for every rotation (write-up §3.2, "the key speed-up").

Per day of the crop's season (FAO-56):
    ETc = Kc(day) * ET0                    what the crop would use with plenty of water
    TAW = AWC * root depth                 water the root zone can hold
    Ks  = 1 if depletion <= p*TAW, else (TAW - depletion) / ((1 - p) * TAW)
    ETa = Ks * ETc                         what it actually uses
Per season (FAO-33):
    yield ratio = max(0, 1 - Ky * (1 - sum ETa / sum ETc))

Irrigated fields refill the bucket (up to the system's daily capacity) whenever
depletion passes p*TAW, and we count the water applied. Rye before a crop has already
used some spring soil water, so that crop starts with the bucket a little drawn down.
"""
import numpy as np


class CropSim:
    """Precomputed season results for every weather year. Build once per dataset."""

    def __init__(self, data):
        w = data["weather"]
        self.site = data["site"].iloc[0].to_dict()
        self.crops = data["crops"].set_index("crop")
        self.soils = dict(zip(data["soils"]["soil"], data["soils"]["awc_mm_per_m"]))
        self.years = np.array(sorted(w["year"].unique()))

        # Daily rain and ET0 as (year, day-of-year) grids; day 366 is 0 in non-leap years.
        n = len(self.years)
        row = np.searchsorted(self.years, w["year"].to_numpy())
        col = w["doy"].to_numpy() - 1
        self.rain = np.zeros((n, 366))
        self.et0 = np.zeros((n, 366))
        self.rain[row, col] = w["PRECTOTCORR"].to_numpy()
        self.et0[row, col] = w["ET0"].to_numpy()

        lo, hi = int(self.site["season_start_doy"]), int(self.site["season_end_doy"])
        self.season_rain = self.rain[:, lo - 1:hi].sum(axis=1)     # May-Sep rain per year, mm
        self._cache = {}

    def awc(self, soil):
        """Available water capacity (mm per m) for a soil texture name."""
        return float(self.soils.get(str(soil).strip().lower(), self.soils["default"]))

    @staticmethod
    def kc_curve(c):
        """FAO-56 crop coefficient for each day of the season: flat, rising, flat, falling."""
        ini, dev, mid, late = (int(c[k]) for k in ("len_ini", "len_dev", "len_mid", "len_late"))
        return np.concatenate([
            np.full(ini, c["kc_ini"]),
            np.linspace(c["kc_ini"], c["kc_mid"], dev, endpoint=False),
            np.full(mid, c["kc_mid"]),
            np.linspace(c["kc_mid"], c["kc_end"], late),
        ])

    def season(self, soil, crop, rye_before, irrigated):
        """Season results for one combination, one value per weather year:
        etc (mm), eta (mm), irrigation (mm), ratio (yield ratio 0-1)."""
        key = (self.awc(soil), crop, bool(rye_before), bool(irrigated))
        if key in self._cache:
            return self._cache[key]
        c = self.crops.loc[crop]
        kc = self.kc_curve(c)
        start = int(c["plant_doy"]) - 1
        days = np.arange(start, start + len(kc))
        taw = key[0] * float(c["root_depth_m"])
        raw = float(c["depletion_p"]) * taw
        cap = float(self.site["irrigation_capacity_mm_per_day"])

        n = len(self.years)
        depletion = np.full(n, min(float(self.site["rye_spring_draw_mm"]), taw) if rye_before else 0.0)
        etc_sum, eta_sum, irr_sum = np.zeros(n), np.zeros(n), np.zeros(n)
        for k, d in enumerate(days):                 # one step per day, all years at once
            if irrigated:
                irr = np.where(depletion > raw, np.minimum(depletion, cap), 0.0)
                depletion -= irr
                irr_sum += irr
            etc = kc[k] * self.et0[:, d]
            ks = np.clip((taw - depletion) / (taw - raw), 0.0, 1.0)
            eta = ks * etc
            depletion = np.clip(depletion - self.rain[:, d] + eta, 0.0, taw)   # extra rain drains away
            etc_sum += etc
            eta_sum += eta

        ratio = np.clip(1 - float(c["ky"]) * (1 - eta_sum / np.maximum(etc_sum, 1e-9)), 0.0, 1.0)
        out = {"etc": etc_sum, "eta": eta_sum, "irrigation": irr_sum, "ratio": ratio}
        self._cache[key] = out
        return out
