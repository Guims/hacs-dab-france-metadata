# DAB+ France Metadata

Version 0.6.0 — expérimentale.

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


## Version 0.6.0
- Surveillance ICY en arrière-plan, partagée par station (3 stations simultanées maximum).
- Bail de 65 secondes renouvelé par les requêtes de la carte ; arrêt après expiration ou arrêt de HA.
- Dernier titre valide conservé côté serveur 90 secondes au maximum ; la carte peut avoir son propre délai d'affichage.
- Icecast JSON conservé, reconnexion après 5 secondes. HTTPS et protection DNS maintenus.
- Une connexion audio supplémentaire consomme de la bande passante. Pas de résolution des identifiants NRJ ni de garantie de titres pendant les publicités. Non testé sur HAOS.


## v0.6.1
- API JSON RadioKing prioritaire pour L'Onde Porteuse et Tsugi Radio (identifiants explicites, à confirmer en conditions HA).
- Repli Icecast/ICY limité à 45 secondes par connexion ; suppression des logs de blocs vides et filtrage des codes alphanumériques simples.
- Les autres stations conservent les méthodes existantes. Pas de couverture nationale API garantie ; Infomaniak exige des identifiants distincts. Pas de pochette ni de validation de fraîcheur API dans cette version.


## v0.6.2 — Radio-Metadata.fr (expérimental)
Priorité au service JSON Radio-Metadata.fr pour les stations du catalogue, puis RadioKing, Icecast et ICY. Requêtes uniquement pour les stations écoutées, intervalle de 60 s en cas de succès, temporisation de 5 à 15 min en cas d'échec. Alias France Inter, France Musique et FIP candidats ; correspondances restantes et fraîcheur non validées. L'API publique est citée sur https://community.roonlabs.com/t/live-radio-metadata-service-incl-bbc-radio-france-flac-and-more/189662?page=11 ; conditions d'intégration tierce à confirmer auprès de l'opérateur. Pas de pochettes affichées dans cette version. Version expérimentale non testée sous HA.
