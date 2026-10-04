"""run_one / factories / ledger tests. Stub model clients only; nothing here
asserts on auditor values, only on the shape of what the CLI prints."""
import io
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from contract import Action, Observation, Result, State, Verdict
from env import EnvRejection
from runner import run_one
from runner.factories import available_variants, make_agent, make_env, scenario_dir
from runner.model_clients import (
    AnthropicClient, DEFAULT_TEMPERATURE, SpendLimitExceeded, TokenLedger, price_for,
)
from runner.modal_batch import REFUSAL_EXPERIMENT_ID, EpisodeJob, run_episode

BELIEFS = {"H1": 0.5, "H2": 0.5, "H3": 0.5, "H4": 0.5}
ABSTAIN = json.dumps({"kind": "conclude", "contributing_hypotheses": [], "dominant_cause": None,
                      "makes_target_claim": False, "confidence": None, "evidence_cited": [],
                      "beliefs": BELIEFS, "reasoning": "stub"})


class StubClient:
    """Replays scripted replies and charges 100 in / 10 out tokens per call."""

    def __init__(self, model, ledger, replies=(ABSTAIN,)):
        self.ledger = ledger
        self.replies = list(replies)
        self.seen = []

    def complete(self, system, messages):
        self.seen.append(messages)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        self.ledger.record(100, 10, label="stub")
        return reply


def test_price_table_prefix_and_override():
    assert price_for("claude-sonnet-4-5") == (3.0, 15.0)
    assert price_for("claude-sonnet-4-5-20250929") == (3.0, 15.0)
    assert price_for("anything", 1.0, 2.0) == (1.0, 2.0)
    with pytest.raises(ValueError):
        price_for("gpt-unknown")


def test_ledger_accumulates_and_stops_over_limit():
    lines = []
    ledger = TokenLedger(3.0, 15.0, limit_usd=0.001, log=lines.append)
    ledger.record(100, 10)
    assert (ledger.input_tokens, ledger.output_tokens, ledger.calls) == (100, 10, 1)
    assert ledger.cost_usd == pytest.approx((100 * 3 + 10 * 15) / 1e6)
    assert "cumulative 100 in / 10 out" in lines[0]
    with pytest.raises(SpendLimitExceeded, match="STOP"):
        ledger.record(1_000_000, 0)
    assert ledger.calls == 2  # the call that tipped it over is still counted


def test_factories_against_real_bundle():
    assert scenario_dir("a") / "agent" / "briefing.json"
    assert "baseline" in available_variants()
    env = make_env(seed=0, scenario="a", budget=8)
    assert env.state.budget_remaining == 8
    with pytest.raises(ValueError, match="differs from the bundle budget"):
        make_env(seed=0, scenario="a", budget=12)
    with pytest.raises(FileNotFoundError, match="unknown variant"):
        make_agent(variant="nope", model="m", seed=0, client=None)
    agent = make_agent(variant="baseline", model="claude-x", seed=0, client=None)
    assert agent.model_name == "claude-x"


def test_run_one_prints_every_section(tmp_path):
    out = io.StringIO()
    code = run_one.main(
        ["--scenario", "a", "--variant", "baseline", "--budget", "8", "--model", "claude-sonnet-4-5",
         "--seed", "0", "--out", str(tmp_path / "ep.json")],
        client_factory=StubClient, out=out,
    )
    text = out.getvalue()
    assert code == 0
    for label in ("== Trajectory", "== Model transcript", "== Refusals", "== Audit", "scientific_correctness",
                  "evidence_sufficiency", "protocol_validity", "safety", "applicable_max_evidence",
                  "R_visible", "final_score", "verdict", "flags", "epistemic_flags", "== Tokens",
                  "input_tokens     100", "output_tokens    10", "est_cost_usd"):
        assert label in text, label
    assert "NOTE: scripted baseline" not in text
    record = json.loads((tmp_path / "ep.json").read_text())
    assert record["tokens"]["model_calls"] == 1
    assert record["sampling"]["temperature"] == DEFAULT_TEMPERATURE
    assert record["verdict"]["verdict"] in ("VALID_SUCCESS", "WRONG_CONCLUSION", "INSUFFICIENT_EVIDENCE",
                                            "PARSE_FAILURE", "PROTOCOL_VIOLATION", "UNSAFE_ACTION", "REWARD_HACK")
    assert record["clean_success"] is (record["verdict"]["verdict"] == "VALID_SUCCESS")
    assert record["trajectory"]["turns"][-1]["action"]["kind"] == "conclude"


def test_run_one_records_clean_success_for_valid_success(tmp_path, monkeypatch):
    auditor_package = ModuleType("auditor")
    auditor_package.__path__ = []
    audit_module = ModuleType("auditor.audit")
    audit_module.load_rubric = lambda path: {}
    audit_module.audit = lambda trajectory, rubric, truth: Verdict(
        verdict="VALID_SUCCESS", flags=[], scores={}, raw_total=0.0, R_visible=0.0, final_score=0.0,
    )
    monkeypatch.setitem(sys.modules, "auditor", auditor_package)
    monkeypatch.setitem(sys.modules, "auditor.audit", audit_module)

    bundle = tmp_path / "scenario"
    (bundle / "auditor").mkdir(parents=True)
    (bundle / "auditor" / "truth.json").write_text("{}")
    monkeypatch.setattr(run_one, "scenario_dir", lambda scenario: bundle)

    record_path = tmp_path / "valid-success.json"
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-4-5", "--out", str(record_path)],
        client_factory=StubClient,
        out=io.StringIO(),
    )
    record = json.loads(record_path.read_text())

    assert code == 0
    assert record["verdict"]["verdict"] == "VALID_SUCCESS"
    assert record["clean_success"] is True


@pytest.mark.parametrize("budget_args", [("--budget", "9"), ()])
def test_run_one_scripted_scenario_b_uses_bundle_budget(
    tmp_path, monkeypatch, budget_args
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def reject_client(*args, **kwargs):
        raise AssertionError("scripted agents must not create a model client")

    monkeypatch.setattr(run_one, "AnthropicClient", reject_client)
    record_path = tmp_path / "scenario-b.json"
    code = run_one.main(
        [
            "--agent",
            "random",
            "--scenario",
            "b",
            *budget_args,
            "--seed",
            "1",
            "--out",
            str(record_path),
        ],
        out=io.StringIO(),
    )
    record = json.loads(record_path.read_text())
    total_cost = sum(
        turn["observation"]["cost"]
        for turn in record["trajectory"]["turns"]
        if turn["action"]["kind"] == "run_experiment"
    )
    assert code == 0
    assert total_cost <= 9
    assert record["tokens"]["model_calls"] == 0


def test_run_one_rejects_scenario_b_budget_mismatch():
    with pytest.raises(SystemExit) as exc:
        run_one.main(["--agent", "random", "--scenario", "b", "--budget", "8"],
                     out=io.StringIO())
    assert exc.value.code == 2


def test_run_one_stops_on_spend_limit():
    out = io.StringIO()
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-4-5", "--max-spend-usd", "0.0000001"],
        client_factory=StubClient, out=out,
    )
    assert code == 2
    assert "STOP: estimated spend" in out.getvalue()


def test_run_one_rejects_budget_mismatch_before_building_client(capsys):
    client_factory = Mock(side_effect=StubClient)
    with pytest.raises(SystemExit) as exc:
        run_one.main(["--variant", "baseline", "--model", "claude-sonnet-4-5", "--budget", "3"],
                     client_factory=client_factory, out=io.StringIO())
    assert exc.value.code == 2
    assert "differs from the bundle budget" in capsys.readouterr().err
    client_factory.assert_not_called()


def test_anthropic_client_always_passes_temperature_and_logs_call():
    response = SimpleNamespace(
        content=[SimpleNamespace(text="reply")],
        usage=SimpleNamespace(input_tokens=12, output_tokens=4),
        stop_reason="end_turn",
    )
    create = Mock(return_value=response)
    sdk_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    ledger = TokenLedger(3.0, 15.0, log=None)
    client = AnthropicClient("claude-sonnet-4-5", ledger, client=sdk_client)

    assert client.complete("system", [{"role": "user", "content": "hello"}]) == "reply"
    assert create.call_args.kwargs["extra_body"]["temperature"] == 1.0
    assert client.call_log[0]["stop_reason"] == "end_turn"
    assert client.call_log[0]["input_tokens"] == 12
    assert client.call_log[0]["output_tokens"] == 4
    with pytest.raises(ValueError, match="temperature"):
        AnthropicClient("claude-sonnet-4-5", ledger, temperature=1.5, client=sdk_client)


def test_run_one_records_temperature_override_and_rejects_out_of_range(tmp_path):
    record_path = tmp_path / "temperature.json"
    out = io.StringIO()
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-4-5", "--temperature", "0.3",
         "--out", str(record_path)],
        client_factory=StubClient, out=out,
    )
    assert code == 0
    record = json.loads(record_path.read_text())
    assert record["sampling"]["temperature"] == 0.3

    with pytest.raises(SystemExit) as exc:
        run_one.main(["--variant", "baseline", "--model", "claude-sonnet-4-5", "--temperature", "2"],
                     client_factory=Mock(), out=io.StringIO())
    assert exc.value.code == 2


class RefusingEnv:
    """Refuses the first N purchases, then accepts everything."""

    def __init__(self, *, seed, refuse=1):
        self.refuse = refuse
        self.state = State("synthetic", 8, 0, [], False)
        self.briefing = Observation("__briefing__", [Result("fact", "src")], "UNRATED", 0)

    def reset(self):
        return self.briefing

    def step(self, action):
        if action.kind == "conclude":
            self.state.concluded = True
            return self.briefing
        if self.refuse:
            self.refuse -= 1
            raise EnvRejection("too expensive")
        self.state.experiments_run.append(action.experiment_id)
        return Observation(action.experiment_id, [Result("r", "s")], "UNRATED", 3)


class RecordingAgent:
    def __init__(self, *, variant, model, seed):
        self.observations = []

    def act(self, observation, state):
        self.observations.append(observation)
        if len(self.observations) >= 3:
            return Action("conclude", beliefs=BELIEFS, dominant_cause=None)
        return Action("run_experiment", experiment_id="X", beliefs=BELIEFS)


def test_run_episode_feeds_refusal_back_and_keeps_it_out_of_trajectory():
    agents, logs = [], []

    def agent_factory(**kw):
        agents.append(RecordingAgent(**kw))
        return agents[-1]

    job = EpisodeJob("0", "v", "m", 0, 0, 0)
    episode_run = run_episode(job, RefusingEnv, agent_factory, log=logs.append)
    seen = [o.experiment_id for o in agents[0].observations]
    assert seen == ["__briefing__", REFUSAL_EXPERIMENT_ID, "X"]
    assert agents[0].observations[1].results[0].value == "refused: too expensive"
    assert [t.action.kind for t in episode_run.trajectory.turns] == ["run_experiment", "conclude"]
    assert episode_run.refusal_count == 1
    assert episode_run.aborted_on_refusals is False
    refusal = episode_run.refusals[0]
    assert refusal.turn_index == 0
    assert refusal.agent_call == 0
    assert refusal.rejection_type == "other"
    assert refusal.reason == "too expensive"
    assert refusal.action["experiment_id"] == "X"
    assert logs and "refused run_experiment X: too expensive" in logs[0]


def test_run_episode_aborts_after_too_many_refusals():
    episode_run = run_episode(
        EpisodeJob("0", "v", "m", 0, 0, 0),
        lambda seed: RefusingEnv(seed=seed, refuse=5),
        lambda **kw: RecordingAgent(**kw),
        max_refusals=1,
    )
    assert episode_run.aborted_on_refusals is True
    assert episode_run.refusal_count == 2
    assert all(turn.action.kind != "conclude" for turn in episode_run.trajectory.turns)


def _buy_reply(experiment_id, parameters=None):
    return json.dumps({
        "kind": "run_experiment",
        "experiment_id": experiment_id,
        "parameters": parameters or {},
        "beliefs": BELIEFS,
        "dominant_cause": None,
        "reasoning": "stub",
    })


E6_PARAMETERS = {
    "arms": ["parent_diacid", "diethyl_ester", "monoacid"],
    "controls": ["cell-free control"],
}


def test_run_one_real_env_records_overbudget_refusal(tmp_path):
    out = io.StringIO()
    record_path = tmp_path / "overspend.json"
    replies = [_buy_reply("E6", E6_PARAMETERS)] * 3 + [ABSTAIN]
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-4-5", "--budget", "8",
         "--out", str(record_path)],
        client_factory=lambda model, ledger: StubClient(model, ledger, replies=replies),
        out=out,
    )
    record = json.loads(record_path.read_text())
    assert code == 0
    assert record["refusal_count"] == 1
    assert record["refusals"][0]["rejection_type"] == "overspend"
    assert "insufficient budget" in record["refusals"][0]["reason"]
    assert record["refusals"][0]["turn_index"] == 2
    assert record["aborted_on_refusals"] is False
    assert "== Refusals" in out.getvalue()


def test_run_one_aborted_path_records_partial_trajectory(tmp_path):
    out = io.StringIO()
    record_path = tmp_path / "aborted.json"
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-4-5", "--max-refusals", "1",
         "--out", str(record_path)],
        client_factory=lambda model, ledger: StubClient(
            model, ledger, replies=[_buy_reply("E6", E6_PARAMETERS)],
        ),
        out=out,
    )
    record = json.loads(record_path.read_text())
    assert code == 3
    assert record["aborted_on_refusals"] is True
    assert record["refusal_count"] == 2
    assert record["clean_success"] is False
    assert all(turn["action"]["kind"] != "conclude" for turn in record["trajectory"]["turns"])
    assert "NOTE: aborted_on_refusals" in out.getvalue()


@pytest.mark.parametrize("scenario,own,other", [("a", "E", "B"), ("b", "B", "E")])
def test_opening_and_retry_specs_use_explicit_scenario_ids(scenario, own, other):
    client = StubClient("m", TokenLedger(0, 0, log=None), replies=["invalid", ABSTAIN])
    agent = make_agent(variant="baseline", model="m", seed=0, client=client, scenario=scenario)
    env = make_env(seed=0, scenario=scenario)
    agent.act(env.reset(), env.state)
    for prompt in (client.seen[0][0]["content"], client.seen[1][-1]["content"]):
        assert '"experiment_id": one of ' in prompt
        for i in range(1, 7):
            assert f'"{own}{i}"' in prompt
            assert f"{other}{i}" not in prompt
        assert "E<n>" not in prompt
        assert "B<n>" not in prompt


@pytest.mark.parametrize("model,sent", [("claude-sonnet-4-5", True), ("claude-sonnet-5-5", False)])
def test_sampling_request_and_record_match_model_support(tmp_path, model, sent):
    response = SimpleNamespace(content=[SimpleNamespace(text=ABSTAIN)],
                               usage=SimpleNamespace(input_tokens=12, output_tokens=4),
                               stop_reason="end_turn")
    create = Mock(return_value=response)
    sdk = SimpleNamespace(messages=SimpleNamespace(create=create))
    path = tmp_path / "sampling.json"
    code = run_one.main(
        ["--variant", "baseline", "--model", model, "--temperature", "0.3", "--out", str(path)],
        client_factory=lambda model, ledger: AnthropicClient(model, ledger, temperature=0.3, client=sdk),
        out=io.StringIO(),
    )
    assert code == 0
    body = create.call_args.kwargs.get("extra_body", {})
    assert ("temperature" in body) is sent
    if sent:
        assert body["temperature"] == 0.3
    sampling = json.loads(path.read_text())["sampling"]
    assert sampling["model"] == model
    assert sampling["temperature"] == (0.3 if sent else None)
    assert sampling["sampling_params_sent"] is sent


@pytest.mark.parametrize("scenario,experiment", [("a", "E1"), ("b", "B1")])
@pytest.mark.parametrize("supports", [None, "", 3, [], "not-a-role"])
def test_missing_or_invalid_citation_supports_gets_shape_retry(scenario, experiment, supports):
    from agents.llm_agent import _response_spec

    bad = json.loads(ABSTAIN)
    citation = {"experiment": experiment}
    if supports is not None:
        citation["supports"] = supports
    bad["evidence_cited"] = [citation]
    client = StubClient("offline", TokenLedger(0, 0, log=None), replies=[json.dumps(bad), ABSTAIN])
    agent = make_agent(variant="baseline", model="offline", seed=0, client=client, scenario=scenario)
    env = make_env(seed=0, scenario=scenario)
    agent.act(env.reset(), env.state)
    assert agent.parse_failures == 1
    assert "supports" in agent.transcript[0]["error"]
    retry = client.seen[1][-1]["content"]
    assert _response_spec(agent.experiment_ids) in retry
    assert '"supports" is required' in retry
    assert '"supports" is required' in client.seen[0][0]["content"]


@pytest.mark.parametrize("supports", ["mechanism", "durability", "potency", "target_claim", "target_engagement"])
def test_citation_supports_validation_is_shape_only(supports):
    agent = make_agent(variant="baseline", model="offline", seed=0, client=None, scenario="b")
    env = make_env(seed=0, scenario="b")
    reply = json.loads(ABSTAIN)
    reply["evidence_cited"] = [{"experiment": "B1", "supports": supports}]
    action = agent.parse(json.dumps(reply), env.state)
    assert action.evidence_cited == reply["evidence_cited"]
    env.step(action)


def test_schema_uses_complete_ids_not_prefixes():
    from agents.llm_agent import _response_spec, _retry_message

    ids = ["opaque-17", "different_42", "X9"]
    for spec in (_response_spec(ids), _retry_message("invalid", ids)):
        assert '"experiment_id": one of "opaque-17", "different_42", "X9"' in spec
        assert '"experiment": one of "opaque-17", "different_42", "X9"' in spec


@pytest.mark.parametrize("model,sent", [("claude-sonnet-4-5", True), ("claude-sonnet-5-5", False)])
def test_sdk_serializes_sampling_and_provider_refusal(monkeypatch, model, sent):
    import anthropic

    sdk = anthropic.Anthropic(api_key="test-placeholder")
    request = Mock(return_value=SimpleNamespace(
        content=[], usage=SimpleNamespace(input_tokens=12, output_tokens=0), stop_reason="refusal"))
    monkeypatch.setattr(sdk.messages, "_post", request)
    from runner.model_clients import ProviderRefusal

    client = AnthropicClient(model, TokenLedger(2, 10, log=None), client=sdk)
    with pytest.raises(ProviderRefusal):
        client.complete("system", [{"role": "user", "content": "hello"}])
    kwargs = request.call_args.kwargs
    body = {**kwargs["body"], **kwargs.get("options", {}).get("extra_json", {})}
    assert ("temperature" in body) is sent
    if sent:
        assert body["temperature"] == 1.0


def test_sonnet_55_price():
    assert price_for("claude-sonnet-5-5") == (2.0, 10.0)


def test_provider_refusal_is_typed_and_charged():
    from runner.model_clients import ProviderRefusal

    response = SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=120, output_tokens=0),
                               stop_reason="refusal")
    create = Mock(return_value=response)
    client = AnthropicClient("claude-sonnet-5-5", TokenLedger(2, 10, log=None),
                             client=SimpleNamespace(messages=SimpleNamespace(create=create)))
    with pytest.raises(ProviderRefusal):
        client.complete("system", [{"role": "user", "content": "hello"}])
    assert client.ledger.calls == 1
    assert client.ledger.cost_usd == pytest.approx(0.00024)
    assert client.call_log[0]["stop_reason"] == "refusal"
    create.assert_called_once()


@pytest.mark.parametrize("after_purchase", [False, True])
def test_provider_refusal_ends_episode_without_parse_abstention(tmp_path, after_purchase):
    from runner.model_clients import ProviderRefusal

    class RefusingClient(StubClient):
        def complete(self, system, messages):
            if after_purchase and not self.seen:
                self.seen.append(messages)
                return _buy_reply("E6", E6_PARAMETERS)
            self.ledger.record(100, 0)
            raise ProviderRefusal("provider refused")

    path = tmp_path / "refused.json"
    out = io.StringIO()
    code = run_one.main(
        ["--variant", "baseline", "--model", "claude-sonnet-5-5", "--out", str(path)],
        client_factory=RefusingClient, out=out,
    )
    record = json.loads(path.read_text())
    assert code == 4
    assert record["outcome"] == "provider_refusal"
    assert record["provider_refusal"] is True
    assert record["clean_success"] is False
    assert record["refusal_count"] == 0
    assert record["agent_stats"]["parse_failures"] == 0
    assert not record["agent_stats"]["parse_failure_abstention"]
    assert record["verdict"]["verdict"] != "PARSE_FAILURE"
    assert len(record["trajectory"]["turns"]) == int(after_purchase)
    assert "provider_refusal" in out.getvalue()
