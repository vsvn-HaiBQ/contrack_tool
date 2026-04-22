import { http } from "../../shared/http";
import type { LogtimeRow, LogtimeSaveResult } from "../../shared/types";

export const logtimeApi = {
  source: (date: string) => http<{ date: string; rows: LogtimeRow[]; activities: string[] }>(`/logtime/source?date=${date}`),
  save: (payload: unknown) => http<LogtimeSaveResult[]>("/logtime/save", { method: "POST", body: JSON.stringify(payload) })
};
