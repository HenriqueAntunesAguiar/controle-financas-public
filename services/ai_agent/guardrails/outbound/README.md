# Outbound guardrails

Este pacote está reservado para a validação da resposta produzida pelo AI Manager.

Quando implementado, deverá ter contratos próprios de saída, classificador, prompt e
middleware `after_agent`. Ele não deve reutilizar automaticamente as decisões ou o
prompt do guardrail de entrada, pois os riscos avaliados são diferentes.

Nenhuma lógica de guardrail de saída está implementada neste momento.
