import { t } from "../ds/tokens";
import type { AppKey } from "./types";

/** Each gym app → its categorical hue (dots, tab borders, allowed-site chips).
 *  Keeps color a frontend concern; the API returns app keys, not tokens. */
export const APP_COLOR: Record<AppKey, string> = {
  shop: t.deltaBlue,
  market: t.deltaAmber,
  calendar: t.deltaEmerald,
  mail: t.deltaRose,
  food: t.deltaViolet,
};
