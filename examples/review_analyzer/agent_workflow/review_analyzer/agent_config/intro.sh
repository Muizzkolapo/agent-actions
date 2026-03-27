#!/usr/bin/env bash

# Guarantee terminal reset on exit or interrupt
trap 'printf "\033[0m\033[39m\033[49m"' EXIT

# ── ANSI shortcuts ────────────────────────────────────────
B='\033[1m'
D='\033[2m'
BLU='\033[94m'
GRN='\033[92m'
YLW='\033[93m'
PRP='\033[95m'
CYN='\033[96m'
RST='\033[0m\033[39m\033[49m'   # reset fg + bg explicitly

# ── Coloured badges (bg + white fg — never dark text) ─────
LLM='\033[44m\033[97m LLM  \033[0m\033[39m\033[49m'   # blue bg
TOOL='\033[42m\033[97m TOOL \033[0m\033[39m\033[49m'   # green bg
GATE='\033[43m\033[97m GATE \033[0m\033[39m\033[49m'   # yellow bg

SEP="${D}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"

# ══════════════════════════════════════════════════════════
# SLIDE 1 · Title
# ══════════════════════════════════════════════════════════
clear
printf "\n\n"
printf "  ${PRP}╔══════════════════════════════════════════════════════╗${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    ${B}${PRP}Agent Actions${RST}                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    Declarative context engineering                    ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    for production LLM pipelines                       ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}╚══════════════════════════════════════════════════════╝${RST}\n"
printf "\n\n"
printf "  ${D}github.com/qanalabs/agent-actions${RST}\n"
sleep 2.5

# ══════════════════════════════════════════════════════════
# SLIDE 2 · The framework
# ══════════════════════════════════════════════════════════
clear
printf "\n\n"
printf "  ${B}Not a workflow tool.${RST}  ${D}A context engineering framework.${RST}\n"
printf "\n"
printf "  ${D}In n8n every node sees everything.${RST}\n"
printf "  ${D}Agent Actions controls what each LLM step thinks about.${RST}\n"
printf "\n"
printf "  \033[44m\033[97m Model   \033[0m\033[39m\033[49m  right tool · right cost · per action\n"
printf "  \033[46m\033[97m Context \033[0m\033[39m\033[49m  observe · drop · passthrough\n"
printf "  \033[42m\033[97m Schema  \033[0m\033[39m\033[49m  validated · structured output\n"
printf "  \033[43m\033[97m Guard   \033[0m\033[39m\033[49m  skip LLM calls on low-quality input\n"
sleep 3

# ══════════════════════════════════════════════════════════
# SLIDE 3 · Pipeline DAG
# ══════════════════════════════════════════════════════════
clear
printf "\n"
printf "  ${D}review_analyzer  ·  6 actions  ·  3 vendors${RST}\n"
printf "  ${SEP}\n\n"
printf "  ${LLM}  ${B}extract_claims${RST}      ${D}groq · llama-3.3-70b · drops star_rating${RST}\n"
printf "  ${LLM}  ${B}score_quality${RST}  ${PRP}×3${RST}  ${D}openai · gpt-4o-mini · parallel isolated${RST}\n"
printf "  ${TOOL}  ${B}aggregate_scores${RST}    ${D}tool · deterministic weighted consensus${RST}\n"
printf "  ${GATE}  ${B}guard: score ≥ 6${RST}    ${D}low quality → filtered · no tokens burned${RST}\n"
printf "  ${LLM}  ${B}generate_response${RST}   ${D}anthropic · claude-sonnet${RST}      ${PRP}┐ parallel${RST}\n"
printf "  ${LLM}  ${B}extract_insights${RST}    ${D}openai · gpt-4o-mini${RST}            ${PRP}┘${RST}\n"
printf "  ${TOOL}  ${B}format_output${RST}       ${D}tool · fan-in from both branches${RST}\n"
printf "\n"
printf "  ${SEP}\n"
sleep 4.5

# ══════════════════════════════════════════════════════════
# SLIDE 4 · Demo intro
# ══════════════════════════════════════════════════════════
clear
printf "\n\n"
printf "  ${PRP}╔══════════════════════════════════════════════════════╗${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    ${B}Review Analyzer${RST}                                    ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    6 actions · 3 vendors · parallel consensus          ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    pre-check gates · progressive context disclosure    ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}    ${D}All declared in YAML.${RST}                              ${PRP}║${RST}\n"
printf "  ${PRP}║${RST}                                                      ${PRP}║${RST}\n"
printf "  ${PRP}╚══════════════════════════════════════════════════════╝${RST}\n"
sleep 2.5
