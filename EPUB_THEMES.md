# EPUB Themes

The EPUB converter selects a CSS theme from the collection `set_name`. The base CSS remains active for every EPUB, and a thematic stylesheet is appended when a collection matches.

## Implemented Themes

| Theme | Collections |
| --- | --- |
| Panteons e epicos | Theros, Born of the Gods, Journey into Nyx, Theros: Beyond Death, Kaldheim, Amonkhet, Hour of Devastation |
| Fabulas e folclore | Wilds of Eldraine, Lorwyn Eclipsed, Bloomburrow |
| Cyber-tradicao | Kamigawa: Neon Dynasty |
| Horror gotico | Shadows over Innistrad, Eldritch Moon, Innistrad: Midnight Hunt, Innistrad: Crimson Vow |
| Terror analogico | Duskmourn: House of Horror |
| Aventura e expedicoes | Prologue to Battle for Zendikar, Battle for Zendikar, Oath of the Gatewatch, Zendikar Rising, Ixalan, Rivals of Ixalan, Lost Caverns of Ixalan |
| Intriga urbana | Return to Ravnica, Gatecrash, Dragon's Maze, Guilds of Ravnica, Ravnica Allegiance, War of the Spark, Murders at Karlov Manor |
| Clans e dragões | Khans of Tarkir, Fate Reforged, Dragons of Tarkir, Tarkir: Dragonstorm |
| Horror biomecanico | Phyrexia: All Will Be One, March of the Machine, March of the Machine: The Aftermath |
| Historia de Dominaria | Dominaria, Dominaria United, The Brothers' War |
| Revolucao de Kaladesh | Kaladesh, Aether Revolt |
| Intriga de Fiora | Conspiracy, Conspiracy: Take the Crown |
| Academia de Arcavios | Strixhaven: School of Mages, Secrets of Strixhaven |
| Ruptura da realidade | Reality Fracture |
| Art deco de New Capenna | Streets of New Capenna |
| Western de Thunder Junction | Outlaws of Thunder Junction |
| Corrida de Aetherdrift | Aetherdrift |
| Ficcao de Edge | Edge of Eternities |
| Origens dos planeswalkers | Magic Origins |
| Pride multiversal | Pride Across the Multiverse |
| Antologia | Magic 2013, Modern Masters, Magic 2014, Commander (2013 Edition), Duel Decks: Jace vs. Vraska, Magic 2015, Commander (2014 Edition), Modern Masters 2015, Commander (2015 Edition), Eternal Masters, Core 2019 |

Fonts are embedded from `fonts/` when available: the TTF files listed in the table below (Google Fonts) and, for the Cyber-tradicao, Horror gotico and Terror analogico themes, fonts extracted from the ZIP archives named in `mtg_epub/themes.py`. Check each included license or copyright file before redistribution.

## Without A Theme

Only `Unknown Set` (the `999 - Unknown Set` folder) uses just the base EPUB stylesheet. Every other collection matches a theme via `theme_for_set` in `mtg_epub/themes.py`.

## Coverage And Font Research

The 64 identified collections now have a thematic stylesheet. Only `Unknown Set` remains intentionally unthemed (see above).

| Theme | Five keywords | Fonts used (per `mtg_epub/themes.py` and theme CSS) |
| --- | --- | --- |
| Panteons e epicos | mitologia, marmore, ouro, deuses, epopeia | Headings: Cinzel (`Cinzel.ttf`). Body: base stylesheet. |
| Fabulas e folclore | floresta, manuscrito, magia, aldeia, conto | Headings and drop cap: Cormorant Garamond (`CormorantGaramond.ttf`). Body: base stylesheet. |
| Cyber-tradicao | neon, tecnologia, samurai, assimetria, contraste | h1: Planet Kosmos (`PlanetKosmos.ttf`, from ZIP); h2: Stranger Back in the Night (`StrangerBackInTheNight.ttf`, from ZIP). Body: base stylesheet. |
| Horror gotico | corvo, sangue, lua, igreja, necromancia | Headings and drop cap: Old English Text MT (from ZIP), falling back to UnifrakturMaguntia, then Crimson Text. Crimson Text is also embedded. Body: base stylesheet. |
| Terror analogico | VHS, estatica, fita, glitch, transcricao | Headings, quotes and drop cap: VCR OSD Mono (`VCROSDMono.ttf`, from ZIP). Body: base stylesheet. |
| Aventura e expedicoes | mapa, ruina, deserto, diario, descoberta | Headings and drop cap: Merriweather (`Merriweather.ttf`). Body: base stylesheet. |
| Intriga urbana | guildas, burocracia, arquitetura, investigacao, lei | Headings: Libre Baskerville (`LibreBaskerville.ttf`). Body: base stylesheet. |
| Clans e dragões | clãs, dragões, honra, guerra, caligrafia | Headings: Noto Serif (`NotoSerif.ttf`). Body: base stylesheet. |
| Horror biomecanico | oleo, metal, invasao, compleacao, assimetria | Headings: Space Grotesk (`SpaceGrotesk.ttf`). Body: base stylesheet. |
| Historia de Dominaria | imperio, artefato, mapa, cronica, bronze | Headings: Abril Fatface (`AbrilFatface.ttf`). Body: base stylesheet. |
| Revolucao de Kaladesh | eter, engrenagem, cobre, invenção, rebeliao | Headings: Rajdhani (`Rajdhani.ttf`). Body: base stylesheet. |
| Intriga de Fiora | corte, assassinato, cartas, luxo, conspiracao | Headings: Berkshire Swash (`BerkshireSwash.ttf`). Body: base stylesheet. |
| Academia de Arcavios | academia, faculdades, pesquisa, tinta, magia | Headings: EB Garamond (`EBGaramond.ttf`). Body: base stylesheet. |
| Ruptura da realidade | brutalismo, fratura, eco, multiverso, instabilidade | Body and h1: IBM Plex Sans (`IBMPlexSans.ttf`). |
| Art deco de New Capenna | art deco, mafioso, jazz, diamante, luxo | Headings: Montserrat (`Montserrat.ttf`). Body: base stylesheet. |
| Western de Thunder Junction | western, fronteira, duelo, madeira, procurado | Headings: Rye (`Rye.ttf`). Body: base stylesheet. |
| Corrida de Aetherdrift | velocidade, metal, pista, equipe, combustao | Headings: Audiowide (`Audiowide.ttf`). Body: base stylesheet. |
| Ficcao de Edge | espaco, estrelas, nave, vazio, tecnologia | Headings: Orbitron (`Orbitron.ttf`). Body: base stylesheet. |
| Origens dos planeswalkers | memoria, biografia, despertar, trauma, identidade | Headings: Bitter (`Bitter.ttf`). Body: base stylesheet. |
| Pride multiversal | comunidade, cor, celebracao, identidade, afeto | Headings: Quicksand (`Quicksand.ttf`). Body: base stylesheet. |
| Antologia | variedade, editorial, arquivo, personagens, colecao | Body and headings: Crimson Text (`CrimsonText.ttf`). |

Fonts that are not in `fonts/` fall back to the generic stacks declared in each theme CSS. DaFont fonts should not be embedded without checking the individual license.
