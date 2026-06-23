# 🏆 Memorial e Transmissões da Copa do Mundo FIFA 2026

Este repositório contém uma aplicação automatizada projetada para rastrear, indexar e disponibilizar transmissões ao vivo, replays e melhores momentos dos jogos da **Copa do Mundo FIFA 2026** transmitidos pela **CazéTV** no YouTube. O portal é gerado de forma estática e hospedado via **GitHub Pages**.

---

## 📂 Estrutura de Arquivos (Esqueleto GitHub)

O projeto possui a seguinte estrutura organizada para deploy e automação contínua:

```
├── .github/
│   └── workflows/
│       └── copa_update.yml  # Automação do GitHub Actions que roda a cada hora
├── .gitignore               # Arquivos ignorados pelo Git
├── README.md                # Instruções e documentação do portal (este arquivo)
├── requirements.txt         # Dependências do Python (beautifulsoup4)
├── updater.py               # Script principal (Scraper, Score Parser e Gerador de HTML)
├── matches.json             # Banco de dados de partidas e links do YouTube
├── matches_data.csv         # Arquivo CSV estruturado com placares e links de todos os jogos
├── matches_metrics.json     # Arquivo JSON contendo métricas do torneio e cobertura da CazéTV
├── index.html               # Painel web estático atualizado automaticamente
└── agendar_copa.ps1         # Script PowerShell de agendamento local horário
```

---

## ⚡ Como Funciona a Atualização Contínua

O script `updater.py` executa em segundo plano os seguintes passos:

1. **Varredura no YouTube (CazéTV):** Acessa as abas de "Vídeos" e "Transmissões" no canal oficial da CazéTV no YouTube e extrai dados (títulos, IDs dos vídeos e status de lives ativas).
2. **Associação de Partidas:** Cruza os nomes das seleções de cada partida cadastrada no `matches.json` com os títulos dos vídeos usando um algoritmo de correspondência textual aproximada.
3. **Extração de Placares:** Identifica partidas finalizadas e busca os vídeos de "melhores momentos" ou "jogo completo". Se encontrados, extrai o placar final diretamente do título do vídeo do YouTube usando expressões regulares (ex: `Portugal 2 x 1 Uzbequistão` é convertido em `score_a = 2` e `score_b = 1`).
4. **Atualização de Status:**
   - **Ao Vivo:** Se a partida estiver com transmissão ativa no YouTube, ela entra em destaque no topo da página com o link para assistir.
   - **Finalizado:** Assim que os melhores momentos/replays sobem, o status é alterado de "Agendado"/"Ao Vivo" para "Finalizado", desativando o link de live e ativando os botões de replay e melhores momentos.

---

## 🤖 Automação via GitHub Actions

Para manter a plataforma atualizada conforme os jogos terminam durante o dia, configuramos a automação no GitHub Actions no arquivo `.github/workflows/copa_update.yml`:

* **Execução Horária:** O workflow executa o atualizador de hora em hora (`0 * * * *`).
* **Deploy no GitHub Pages:** Após rodar o script, o bot do GitHub commita as alterações no banco `matches.json` e no `index.html`, disparando o deploy do site estático automaticamente.

---

## 💻 Configuração Local (Windows)

### Instalar Dependências
```bash
pip install -r requirements.txt
```

### Executar Manualmente
```bash
python updater.py
```

### Agendamento Local
Clique com o botão direito no arquivo `agendar_copa.ps1` e selecione **"Executar com o PowerShell"** (ou rode em um terminal de administrador). O script criará uma tarefa do Windows para rodar o atualizador a cada 1 hora.
