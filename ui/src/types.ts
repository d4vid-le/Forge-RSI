export type Summary = {
  n?: number;
  passed?: number;
  score?: number;
  tokens_out?: number;
  cost_per_solved?: number;
  [key: string]: unknown;
};

export type EvalRow = {
  run: string;
  split: string;
  base: Summary;
  gated: Summary;
  delta: number | null;
  routed: number;
  non_routed_identical: boolean | null;
  base_unchanged: boolean | null;
};

export type SkillRow = {
  round: string;
  skill: string;
  status: string;
  adapter?: string | null;
  adapter_exists: boolean;
  rows?: number | null;
  iters?: number | null;
  train_loss?: number | null;
  val_loss?: number | null;
  base_unchanged?: boolean | null;
  decision?: { reason?: string; status?: string; [key: string]: unknown };
};

export type RsiIteration = {
  round: string;
  iteration: number;
  candidate: string;
  wins?: number;
  losses?: number;
  ties?: number;
  candidate_score?: number;
  delta?: number;
  accepted?: boolean;
  reason?: string;
  candidate_cost?: number;
};

export type RsiHoldout = {
  round: string;
  baseline_score?: number;
  final_score?: number;
  delta?: number;
  not_worse?: boolean;
  winner_harness?: string;
};

export type DreamPolicy = {
  policy: string;
  passed: number;
  n: number;
  score: number;
  calls: number;
  tokens_out: number;
  cost_per_solved?: number | null;
  value: number;
};

export type Dream = {
  run_id: string;
  harness?: string | null;
  winner: string;
  note?: string;
  policies: DreamPolicy[];
};

export type GapCluster = {
  key: string;
  failed: number;
  total: number;
  by_error: Record<string, number>;
  verified_rows: number;
  missing: number;
};

export type Gaps = {
  run_id: string;
  split: string;
  generated_at: string;
  summary: Summary;
  clusters: GapCluster[];
  corpus?: {
    file: string;
    rows: number;
    verified: number;
    by_kind: Record<string, number>;
    missing: number;
  } | null;
  policy?: string;
};

export type Holdout = {
  exists: boolean;
  count: number;
  created_at?: string | null;
  seed?: number | null;
  combined_sha256?: string | null;
  archives: number;
  latest_archive?: string | null;
  error?: string;
};

export type OpsStatus = {
  generated_at: string;
  project: string;
  base: { path: string; exists: boolean; checksums_ok: boolean | null };
  tasks: {
    counts: Record<string, number>;
    lint: { ok: boolean; n: number; failures: unknown[] };
  };
  skills: SkillRow[];
  evaluations: EvalRow[];
  rsi: { iterations: RsiIteration[]; holdout: RsiHoldout[] };
  composition: {
    configs?: Record<string, {
      parts_word?: number; parts_word_n?: number;
      parts_merge?: number; parts_merge_n?: number;
      whole_pass: number; whole_n: number;
    }>;
    parts_tasks?: string[];
  };
  private_decision: {
    promote?: boolean;
    reason?: string;
    private_delta?: number;
    public_dev_delta?: number;
    public_probe_delta?: number;
    forgetting_ok?: boolean;
  };
  dream?: Dream | null;
  gaps?: Gaps | null;
  holdout?: Holdout | null;
  reports: { name: string; bytes: number; modified: string }[];
};

export type Session = {
  id: string;
  name?: string;
  created_at?: string;
  updated_at?: string;
  sources?: string;
  stats?: string;
};

export type Row = {
  id: number;
  session: string;
  decision: string;
  flags: string[];
  domain?: string;
  schema?: string;
  source_file?: string;
  source_line?: number;
  est_tokens?: number;
  char_len?: number;
  note?: string;
  edited?: boolean;
  messages: { role: string; content: string }[];
  original?: { role: string; content: string }[] | null;
  meta?: Record<string, unknown>;
};

export type SessionCounts = {
  total?: number;
  by_decision?: Record<string, number>;
  by_domain?: Record<string, number>;
  by_schema?: Record<string, number>;
  by_flag?: Record<string, number>;
  quarantine?: Record<string, number>;
};

export type ForgeModel = {
  id: string;
  label: string;
  kind: string;
  path: string;
  size_gb: number;
  lock?: string | null;
};

export type ForgeAdapter = {
  name: string;
  path: string;
  format: string;
  size_mb: number;
  modified?: string;
  rank?: number | null;
  scale?: number | null;
  num_layers?: number | null;
};

export type ForgeRun = {
  name: string;
  status?: string;
  adapter_path?: string;
  data?: { train?: number; valid?: number };
  last_train?: { iter?: number; loss?: number; tok_sec?: number; it_sec?: number; mem?: number };
  last_val?: { iter?: number; loss?: number };
  train?: { iter: number; loss: number }[];
  tail?: string[];
};

export type ForgeStatus = {
  machine: { platform: string; python: string };
  mlx: {
    mlx?: string | null;
    mlx_lm?: string | null;
    lora_cli?: string | null;
    python?: string;
    server_cli?: string | null;
  };
  models: ForgeModel[];
  adapters: ForgeAdapter[];
  runs: ForgeRun[];
  runs_dir?: string;
  adapters_dir?: string;
};

export type PlaygroundEndpoint = {
  label: string;
  url: string;
  kind: string;
  models: string[];
};

export type PlaygroundStatus = {
  endpoints: PlaygroundEndpoint[];
  servers?: Record<string, { running: boolean; models?: string[]; [key: string]: unknown }>;
};

export type JobStep = {
  name: string;
  cmd: string[];
  status: string;
  exit_code?: number | null;
  started?: string | null;
  finished?: string | null;
  gate?: boolean;
  guard?: string;
  index?: number;
};

export type Job = {
  id: string;
  kind: string;
  params: Record<string, unknown>;
  steps: JobStep[];
  status: string;
  created: string;
  started?: string | null;
  finished?: string | null;
  approved?: boolean | null;
  note?: string;
  current?: number;
  pid?: number | null;
  log: string;
};

export type ChatResponse = {
  text: string;
  model?: string;
  endpoint?: string;
  wall_ms?: number;
  ttft_ms?: number;
  tok_s?: number;
  usage?: { completion_tokens?: number; [key: string]: unknown };
};
