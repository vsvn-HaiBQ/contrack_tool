import { http } from "../../shared/http";

export type VersionBundle = {
  bundleId: string; displayName: string; databaseSchema: string; status: string;
  error: string | null; defaultDatabaseId: string; defaultRepositoryId: string;
};
export type Catalog = {
  enabled: boolean; busy: boolean; message?: string; versions: VersionBundle[];
  databases: Array<{ id: string; schema: string; profile: string }>;
  repositories: Array<{ id: string; type: string; name: string }>;
};
export type Recipe = {
  bundle: string; display_name: string; war: string; schema_version: string;
  database_baseline: string; repository: string; repository_type: string; working_database?: string;
};
export type Environment = Recipe & {
  database: string; run_id: string; status: string; checked_at?: string; updated_at?: string;
};
export type EnvironmentRun = {
  run_id: string; display_name: string; bundle_id: string; actor: string; status: string;
  working_database: string; created_at: string; updated_at: string; failed_step: string | null;
  error: { code: string; message: string } | null; steps: Record<string, string>;
  log?: string; recipe?: Recipe; request?: Record<string, unknown>;
};
export type Selection = {
  bundle_id: string; database_profile_id: string; repository_profile_id: string;
};

const base = "/contrack-environments";
export const environmentsApi = {
  catalog: () => http<Catalog>(`${base}/catalog`),
  current: () => http<{ environment: Environment | null; busy: boolean }>(`${base}/current`),
  runs: (offset = 0) => http<{ items: EnvironmentRun[]; total: number; limit: number; offset: number }>(`${base}/runs?limit=10&offset=${offset}`),
  run: (id: string) => http<EnvironmentRun>(`${base}/runs/${encodeURIComponent(id)}`),
  validate: (selection: Selection) => http<{ valid: boolean; recipe: Recipe }>(`${base}/validate`, {
    method: "POST", body: JSON.stringify(selection),
  }),
  prepare: (selection: Selection) => http<EnvironmentRun>(`${base}/prepare`, {
    method: "POST", body: JSON.stringify(selection),
  }),
};
