// Livro de set: capa, sumário, marcadores no PDF e os contos incluídos pelo wrapper.
// Compilado para PDF ("paged"); para HTML mantém o comportamento antigo (título + contos).
//
// `cover` recebe CONTEÚDO, não caminho (caminhos em pacote resolvem a partir do pacote):
//   #show: doc => conf("Bloomburrow", cover: image("057 - Bloomburrow/001_.../01.jpg"), doc)
#import "@local/mtgstory:0.2.0": theme-for, page-paper, page-margin, scene-ornament

#let conf(set_name, cover: none, doc) = {
    let theme = theme-for(set_name)
    let with_images = sys.inputs.at("with_images", default: "true")
    context if target() == "paged" {
        set page(paper: page-paper, margin: page-margin, header: none, footer: none)
        set text(font: theme.body-font, size: 10.5pt, lang: "en", hyphenate: true)

        // Capa: nome do set grande (título de nível 1, só nos marcadores do PDF) e arte opcional.
        {
            set par(justify: false)
            set text(hyphenate: false)
            show heading.where(level: 1): it => align(center, block(
                width: 100%,
                text(font: theme.title-font, fill: theme.accent, size: 34pt, weight: "regular", it.body),
            ))
            align(center)[
                #v(1.2cm)
                #text(size: 10pt, tracking: 0.18em)[#smallcaps[Magic: The Gathering]]
                #v(1.1cm)
                #heading(level: 1, outlined: false, bookmarked: true, set_name)
                #scene-ornament(theme.accent)
                #text(size: 10pt, style: "italic", fill: luma(100))[Stories]
            ]
            if cover != none and with_images == "true" {
                v(1fr)
                set image(width: 100%, height: 100%, fit: "cover")
                block(width: 100%, height: 48%, clip: true, cover)
            }
        }

        // Sumário: só os títulos dos contos (nível 2); subtítulos internos não entram.
        pagebreak()
        {
            set par(justify: false, first-line-indent: 0pt)
            // Sem `outline(title:)`: esse título seria um heading de nível 1 e quebraria o aninhamento
            // dos marcadores do PDF (set > contos).
            align(center, text(font: theme.title-font, fill: theme.accent, size: 18pt)[Contents])
            v(1em)
            outline(title: none, target: heading.where(level: 2, outlined: true), depth: 2)
        }
        doc
    } else {
        [
            #set text(size: 24pt)
            #set align(center + horizon)
            #heading(level: 1)[#set_name]
        ]
        doc
    }

    // Por último, para valer sobre os `set document` dos contos incluídos (o último vence).
    set document(title: set_name, author: "Wizards of the Coast")
}
