# Un lot complet : enrichissement -> verification des domaines -> export.
# Relancer autant de fois que voulu, la file reprend ou elle s'etait arretee.
#
#   .\lancer-lot.ps1                          # 8000 structures, gratuit
#   .\lancer-lot.ps1 -Moteur brave            # consomme le quota mensuel
#   .\lancer-lot.ps1 -Limite 3000 -ScoreMin 70
#
# Le moteur par defaut est `devine` : gratuit et illimite, mais il ne retrouve
# le site que d'une structure sur trois a six. `brave` et `google` trouvent
# beaucoup mieux et sont donc a garder pour les lots qui comptent.

param(
    [int]$Limite = 8000,
    [ValidateSet("devine", "brave", "google", "aucun")]
    [string]$Moteur = "devine",
    [int]$BudgetMoteur = 300,
    [int]$Paralleles = 8,
    [int]$ScoreMin = 60
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$horodat = Get-Date -Format "yyyy-MM-dd-HHmm"
$sortie = "exports\leads-$horodat.xlsx"

Write-Host "== Enrichissement ($Limite structures, moteur $Moteur) ==" -ForegroundColor Cyan
python -m leadgen enrichir --limite $Limite --moteur $Moteur `
                           --budget-moteur $BudgetMoteur --paralleles $Paralleles

Write-Host "== Verification des domaines ==" -ForegroundColor Cyan
python -m leadgen verifier

Write-Host "== Export ==" -ForegroundColor Cyan
python -m leadgen exporter --out $sortie --score-min $ScoreMin

Write-Host "== Etat de la base ==" -ForegroundColor Cyan
python -m leadgen stats

Write-Host "`nFichier pret : $sortie" -ForegroundColor Green
Write-Host "Rappel : lien de desinscription + votre identite dans chaque mail." -ForegroundColor Yellow
