from agents.security_prover.output import SecurityProverOutput, PolicyViolation, ProofTrace

__all__ = ["security_prover_agent", "SecurityProverOutput", "PolicyViolation", "ProofTrace"]


def __getattr__(name: str):
    if name != "security_prover_agent":
        raise AttributeError(name)
    from agents.security_prover.agent import security_prover_agent

    globals()[name] = security_prover_agent
    return security_prover_agent
