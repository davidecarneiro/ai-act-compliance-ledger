# Shared path resolution for the shell scripts of the prototype.
#
# The same tree is used in two places: the dissertation vault, where the code
# lives under 04_projeto/prototype/ and the results under 06_dados/experiments/,
# and the folder delivered with the manuscript, where they sit side by side as
# prototype/ and experiments/. Reviewers run the second one on their own
# machines, so nothing here may assume an absolute path.
#
# Usage:  source "$(dirname "${BASH_SOURCE[0]}")/../delivery_paths.sh"
# Sets:   PROTOTYPE_DIR and EXPERIMENTS_DIR (the latter honoured if pre-set).

_find_experiments() {
  local dir="$1"
  while [ "$dir" != "/" ]; do
    if [ -d "$dir/06_dados" ] && [ -d "$dir/04_projeto" ]; then
      echo "$dir/06_dados/experiments"; return
    fi
    if [ -d "$dir/prototype" ] && [ -d "$dir/experiments" ]; then
      echo "$dir/experiments"; return
    fi
    dir="$(dirname "$dir")"
  done
  echo ""
}

PROTOTYPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${EXPERIMENTS_DIR:-}" ]; then
  EXPERIMENTS_DIR="$(_find_experiments "$PROTOTYPE_DIR")"
  [ -n "$EXPERIMENTS_DIR" ] || EXPERIMENTS_DIR="$PROTOTYPE_DIR/../experiments"
fi
# The folder of one complete run, wherever it is filed: the vault keeps them
# directly under experiments/, the delivered folder in a runs/ drawer. Reading
# prefers whichever exists; writing prefers the drawer when there is one.
run_dir() {
  local nome="$1"
  if [ -d "$EXPERIMENTS_DIR/runs/$nome" ]; then echo "$EXPERIMENTS_DIR/runs/$nome"
  elif [ -d "$EXPERIMENTS_DIR/$nome" ]; then echo "$EXPERIMENTS_DIR/$nome"
  elif [ -d "$EXPERIMENTS_DIR/runs" ]; then echo "$EXPERIMENTS_DIR/runs/$nome"
  else echo "$EXPERIMENTS_DIR/$nome"; fi
}

export PROTOTYPE_DIR EXPERIMENTS_DIR
