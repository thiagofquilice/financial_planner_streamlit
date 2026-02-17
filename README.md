# Assistente Financeiro em Streamlit

## Visão geral
O projeto `financial_planner_streamlit` implementa um assistente financeiro de múltiplas etapas construído em Python e Streamlit. Ele orienta o usuário no cadastro dos dados de um negócio (nome, moeda, horizonte de planejamento), estrutura de receitas, custos variáveis, custos fixos operacionais, investimentos e financiamento. O modelo de resultado utiliza **custeio variável** (margem de contribuição separada de custos fixos), com projeções, indicadores de viabilidade e relatórios em PDF/Excel.

## Requisitos
Instale as dependências mínimas listadas no arquivo `requirements.txt` ou utilize o comando abaixo em um ambiente virtual Python 3.9+.【F:requirements.txt†L2-L8】

```bash
pip install -r requirements.txt
```

## Como executar
1. Certifique-se de que todas as dependências estejam instaladas.
2. No diretório do projeto, execute o comando:
   ```bash
   streamlit run streamlit_app.py
   ```
3. O navegador abrirá a interface do assistente na porta padrão do Streamlit (geralmente `http://localhost:8501`).

> Dica: você pode executar o app em servidores remotos configurando o Streamlit para modo headless (`streamlit run streamlit_app.py --server.headless true`).

## Fluxo do assistente passo a passo
O aplicativo é estruturado em sete etapas acessadas sequencialmente pelos botões "Próximo" e "Voltar" exibidos ao fim de cada tela.【F:streamlit_app.py†L1034-L1883】 A navegação corrente também aparece no topo de cada etapa por meio de um índice visual.

1. **Etapa 1 – Identificação do Projeto**: informe o nome do projeto, moeda de trabalho, horizonte (número de anos) e, opcionalmente, habilite o cálculo de tributos do Simples Nacional selecionando o anexo aplicável. Nesta tela você também pode salvar o estado atual do projeto em JSON ou carregar um arquivo previamente salvo.【F:streamlit_app.py†L1034-L1124】
2. **Etapa 2 – Estrutura de Receitas**: cadastre produtos ou serviços, definindo preço, quantidade e percentual vendido a prazo. Escolha entre preencher uma tabela mensal completa ou gerar automaticamente a série a partir de valores base e crescimento. Os dados mensais são armazenados para todo o horizonte de projeção e podem ser ajustados manualmente.【F:streamlit_app.py†L1127-L1349】
3. **Etapa 3 – Custos Variáveis Diretos e Despesas Variáveis**: para cada produto/serviço, inclua itens variáveis por unidade (quantidade × valor unitário) e despesas variáveis associadas (como taxas ou comissões). Esses valores alimentam o cálculo do custo variável unitário e da margem de contribuição.【F:streamlit_app.py†L1356-L1478】
4. **Etapa 4 – Custos Fixos Operacionais (Opex)**: organize custos fixos nas categorias Operacionais, Administrativas e de Vendas. Informe descrições e valores mensais para compor o custo fixo usado nas análises de ponto de equilíbrio e fluxo de caixa.【F:streamlit_app.py†L1481-L1527】
5. **Etapa 5 – Investimentos (CapEx)**: liste ativos imobilizados ou investimentos iniciais, informando descrição, valor e mês de aquisição (0 para desembolsos iniciais).【F:streamlit_app.py†L1530-L1568】
6. **Etapa 6 – Estrutura de Capital**: registre eventuais financiamentos, especificando valor, taxa de juros anual e prazo em anos. O aplicativo calcula automaticamente a parcela anual e considera o pagamento nas projeções de resultado e caixa.【F:streamlit_app.py†L1571-L1603】
7. **Etapa 7 – Resultados e Análises**: ajuste cenários variando a quantidade vendida e definindo a taxa de desconto para calcular VPL. Visualize DRE em **custeio variável** (receita, custos variáveis, margem de contribuição implícita, custos fixos e resultado), fluxo de caixa com financiamento separado, indicadores de viabilidade (VPL, TIR, TIRm, payback), ponto de equilíbrio por produto e tabelas mensais/anuais em competência e caixa.【F:streamlit_app.py†L1606-L1870】

## Exportação de relatórios e backup de dados
- Utilize o botão **Salvar projeto (JSON)** na Etapa 1 para exportar todos os dados inseridos; o mesmo painel permite carregar um JSON previamente salvo e continuar o trabalho do ponto onde parou.【F:streamlit_app.py†L1085-L1124】
- Na Etapa 7 você encontra botões para baixar um resumo em PDF e Excel, além de um relatório completo com projeções, indicadores e análises de ponto de equilíbrio.【F:streamlit_app.py†L1709-L1775】

## Boas práticas de uso
- Revise o horizonte de planejamento antes de avançar para a Etapa 2: a duração define o número de meses exibidos em todas as tabelas de entrada.【F:streamlit_app.py†L1170-L1180】
- Sempre que ajustar um valor base ou percentual de crescimento na Etapa 2, utilize o botão **Gerar valores mensais** para preencher novamente a série e, se necessário, personalize os meses manualmente.【F:streamlit_app.py†L1181-L1349】
- Explore simulações na Etapa 7 alterando a variação de vendas e a taxa de desconto para comparar cenários pessimistas e otimistas; os gráficos e tabelas são atualizados instantaneamente.【F:streamlit_app.py†L1632-L1699】
- Caso deseje reiniciar o processo do zero, utilize o botão **Reiniciar** exibido ao final da Etapa 7. O aplicativo limpa todo o `session_state` e reabre a Etapa 1.【F:streamlit_app.py†L1871-L1883】

## Suporte e contribuição
Sinta-se à vontade para abrir issues ou pull requests descrevendo melhorias desejadas. Ao contribuir, mantenha este guia atualizado para refletir novas etapas ou funcionalidades.
