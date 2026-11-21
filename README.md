# DAB+ France Metadata

Version 0.5.4 — expérimentale.

Complément facultatif de [DAB+ France](https://github.com/Guims/hacs-dab-france). Récupération ICY côté serveur Home Assistant.

## Installation HACS

Ajouter ce dépôt personnalisé dans la catégorie Intégration, télécharger la branche main, redémarrer Home Assistant, puis Paramètres > Appareils et services > Ajouter une intégration > DAB+ France Metadata. Aucun YAML nécessaire. Carte DAB+ France v0.5.0 ou ultérieure requise.

## Changelog

- 0.5.4 : jusqu'à trois redirections HTTPS pour ICY, destinations publiques uniquement, sans identifiants dans les URL. Lecture de huit blocs ICY au maximum dans le budget de dix secondes. Non testé sur HAOS.

- 0.5.3 : recherche Icecast JSON côté serveur avant ICY, diagnostic HTTP, type de contenu, intervalle ICY et StreamTitle tronqué. URL journalisée sans query string. Redirections toujours désactivées ; budget de 10 secondes par flux. Non testé sur HAOS.

- 0.5.2 : filtrage des titres sans lettres et diagnostics debug via le logger dab_france_metadata. Les identifiants propriétaires ne sont pas résolus.

- 0.5.1 : dépôt indépendant, configuration graphique, traduction française.
- 0.5.0 : récupération ICY serveur avec catalogue HTTPS, cache et limitation des connexions.

## Limites

Non testé sur HAOS. Les redirections vers HTTP et les flux dépourvus de métadonnées restent non pris en charge. Le module ne fournit pas encore les API propriétaires ni les pochettes. Un redémarrage est nécessaire pour désactiver complètement le service après suppression de l'intégration.
