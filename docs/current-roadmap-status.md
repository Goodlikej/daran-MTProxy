# Current roadmap status

Дата: 2026-03-28
Статус: active working summary

## Purpose

Этот файл нужен не для красоты.
Он фиксирует в repo-visible форме:
- что уже сделано
- что подтверждено
- что не готово
- какой следующий блок брать

Цель — убрать вечный бардак вида "а что именно мы уже сделали и что осталось".

## Project position

Проект: `daran-proxy-stack` / `daran-MTProxy`

Целевое направление:
- terminal-first installer/control product for VPS
- optional panel as secondary function
- truthful observed state as the only source of truth

## What is already done

### Foundation already present
- API/control-plane scaffold exists
- minimal panel scaffold exists
- bootstrap/run/systemd scripts exist
- smoke test baseline exists
- WARP/Cascade groundwork exists
- repo is already on GitHub

### Verified historical progress
- panel bootstrap on Ubuntu 24.04 was brought to working state after dependency fixes
- TemplateResponse/Jinja crash was fixed earlier
- test baseline was previously green (`100 passed, 26 skipped`)
- initial discovery/truthful-state direction was already identified as the critical next block

### Newly fixed at planning/spec level
- primary product shape is now locked as terminal-first
- panel is explicitly downgraded to optional function, not primary UX
- menu tree is now defined
- implementation phases are now defined
- truthful observed state model is now defined as required architecture

## Repo-visible planning artifacts added in this pass

### 1. Terminal-first product shape
File:
- `docs/terminal-first-product-shape.md`

Commit:
- `14c7469` — `docs(product): define terminal-first menu roadmap`

What it defines:
- primary product direction
- menu tree
- module order
- same-VPS vs remote-panel modes
- implementation phases
- git and delivery discipline

### 2. Truthful observed state model
File:
- `docs/observed-state-model.md`

Commit:
- `4bc1b28` — `docs(state): define truthful observed state model`

What it defines:
- desired vs configured vs observed state
- shared module contract
- health dictionaries
- module-specific state contracts
- discovery confidence rules
- re-discover and first-run reconcile rules

## What is not done yet

### Product/runtime gaps
- no terminal menu implementation yet
- no real observed-state snapshot implementation yet
- no truthful discovery implementation for modules yet
- no first-run reconcile implementation yet
- panel still not rewired to the future truthful state backend

### Module gaps
- WARP module is not yet implemented against the new state contract
- MTProxy module is not yet implemented against the new state contract
- Cascade rule manager is not yet implemented against the new state contract
- Xray / Xray Pro / AmneziaWG discovery and management are not yet implemented in this new architecture

### Delivery gaps
- current repo still contains unrelated uncommitted working changes outside the new docs
- no fresh implementation checkpoint commit exists yet for discovery backend
- no repo-visible implementation status file existed before this one

## Current verified truth

As of this checkpoint, what is true:
- planning direction is no longer ambiguous
- panel-first drift is explicitly rejected
- truthful discovery/state is now a required architectural constraint
- repo now contains explicit implementation phases and module/state contracts

As of this checkpoint, what is not yet true:
- the terminal-first product is not implemented yet
- module discovery is not yet truthful in code
- panel is not yet proven to reflect observed truth

## Recommended next block

### Next block: discovery backend MVP

Goal:
- implement the first truthful observed-state backend and re-discover flow

Scope:
1. define concrete runtime snapshot file/module shape in code
2. implement host-level discovery
3. implement WARP detection
4. implement MTProxy detection
5. implement initial Cascade detection
6. expose re-discover action
7. return stable structured results for terminal and panel use

Done means:
- product can inspect the machine and produce observed truth instead of inferred defaults

## After that

### Next-after-next block: terminal menu MVP
Only after discovery backend exists.

Scope:
- main menu
- install menu
- manage menu
- diagnostics menu
- panel options menu

Done means:
- product becomes usable through SSH without depending on web panel

## Delivery discipline from this point

Every future implementation block must leave repo-visible evidence of:
- completed scope
- verified current behavior
- known remaining gaps
- next recommended block

Minimum acceptable form:
- commit message
- updated docs/status file
- if pushed, GitHub-visible history that makes the above obvious

## Branch/commit rule

Do not pile unrelated work into one commit.

Expected pattern:
1. pick one narrow block
2. implement it
3. verify it
4. commit it
5. update this file if project state changed

Accepted working states should be committed before the next block starts.

## Current next action

If continuing now, the correct next implementation target is:
- discovery backend MVP

Not:
- panel polish
- cosmetic UI work
- multi-node control
- decorative dashboard work

Because without truthful discovery, those are just prettier lies.
