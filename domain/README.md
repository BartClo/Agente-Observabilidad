# domain/

Logica de negocio pura, sin imports de deepagents/LangChain/LangGraph. Un test
(agregado en la etapa 2, junto con `domain/parafiscal_core/`) verifica esto ultimo.

Cada `agents/<agente>/tools.py` llama funciones de aqui; el LLM nunca calcula, solo
elige que tool llamar.
