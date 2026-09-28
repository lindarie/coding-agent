// Usage: pnpm cli "Add a fibonacci function and tests" --workspace demo
//   env: AGENT_URL (default http://localhost:8000), AGENT_API_TOKEN
//   flags: -w/--workspace, --model, --max-iterations, --json (raw events, one per line)
import { streamRun, type AgentEvent } from "@coding-agent/api-types";

const args = process.argv.slice(2);
let workspace = "demo";
let model: string | undefined;
let maxIterations: number | undefined;
let raw = false;
const words: string[] = [];
for (let i = 0; i < args.length; i++) {
  const a = args[i]!;
  if (a === "-w" || a === "--workspace") workspace = args[++i] ?? workspace;
  else if (a === "--model") model = args[++i];
  else if (a === "--max-iterations") maxIterations = Number(args[++i]);
  else if (a === "--json") raw = true;
  else words.push(a);
}
const task = words.join(" ").trim();
if (!task) {
  console.error('Usage: pnpm cli "<task>" [--workspace demo] [--model name] [--max-iterations n] [--json]');
  process.exit(2);
}

const c = (code: number, s: string) => (process.stdout.isTTY ? `\x1b[${code}m${s}\x1b[0m` : s);

function print(ev: AgentEvent): void {
  switch (ev.type) {
    case "agent_started": return console.log(c(2, `▶ run ${ev.run_id} · ${ev.model} · ${ev.workspace}`));
    case "status": return console.log(c(2, `… ${ev.message}${ev.iteration ? ` (#${ev.iteration})` : ""}`));
    case "agent_message": return console.log(`\n${ev.content}\n`);
    case "tool_call": return console.log(c(33, `🔧 ${ev.tool}`) + " " + JSON.stringify(ev.arguments).slice(0, 200));
    case "tool_result": return console.log(c(ev.success ? 32 : 31, `   ${ev.success ? "✓" : "✗"} ${ev.output.split("\n")[0]?.slice(0, 120) ?? ""}`));
    case "file_changed": return console.log(c(35, `📝 ${ev.change} ${ev.path} (${ev.bytes} B)`));
    case "command_started": return console.log(c(36, `$ ${ev.command}`));
    case "command_finished":
      console.log(ev.output.trimEnd().split("\n").map((l) => "  │ " + l).join("\n"));
      return console.log(c(ev.exit_code === 0 ? 32 : 31, `  exit ${ev.timed_out ? "timeout" : ev.exit_code} (${ev.duration_s}s)`));
    case "error": return console.error(c(31, `⚠ ${ev.message}`));
    case "agent_finished":
      console.log(c(ev.status === "completed" ? 32 : 31, `\n■ ${ev.status} after ${ev.iterations} iterations`));
      if (ev.git_branch) console.log(`  branch: ${ev.git_branch}`);
      if (ev.diff_stat) console.log(ev.diff_stat);
  }
}

let last: AgentEvent | undefined;
try {
  for await (const ev of streamRun(
    { task, workspace, model, max_iterations: maxIterations },
    { baseUrl: process.env.AGENT_URL ?? "http://localhost:8000", token: process.env.AGENT_API_TOKEN },
  )) {
    last = ev;
    raw ? console.log(JSON.stringify(ev)) : print(ev);
  }
} catch (e) {
  console.error(c(31, `Request failed: ${(e as Error).message}`));
  process.exit(1);
}
process.exit(last?.type === "agent_finished" && last.status === "completed" ? 0 : 1);
