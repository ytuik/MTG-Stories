// Template dos guias. Mesma tipografia dos contos (mtgstory); no HTML mantém o layout antigo.
#import "@local/mtgstory:0.2.0": theme-for, book-style, scene-ornament

#let conf(
    title,
    date: datetime(day: 05, month: 08, year: 1993),
    author: "Unknown author",
    doc
) = {
    let theme = theme-for("Planeswalker's Guide")
    let with_images = sys.inputs.at("with_images", default: "true")
    show figure: it => if with_images == "true" { it }
    set document(title: title, author: author, date: date)
    context if target() == "paged" {
        show: book-style.with(theme, title, "Planeswalker's Guide")
        {
            set par(justify: false)
            set text(hyphenate: false)
            v(1.6cm)
            align(center)[
                #[#heading(level: 1, outlined: true, bookmarked: true)[#text(
                    font: theme.title-font, fill: theme.accent, size: 24pt, weight: "regular", title,
                )]<story-title>]
                #v(0.6em)
                #text(size: 11pt, tracking: 0.08em)[#smallcaps(author)]
                #v(0.2em)
                #text(size: 9pt, style: "italic", fill: luma(100))[#date.display("[day]. [month]. [year]")]
                #scene-ornament(theme.accent)
            ]
        }
        set image(height: 40%)
        set heading(outlined: false)
        doc
    } else {
        {
            set align(center)
            par(spacing: 2.00em)[#text(size: 3.5em, weight: "bold")[#title]]
            par()[#text(size: 2.5em)[#author]]
        }
        {
            set text(size: 1.5em)
            set align(center)
            [#date.display("[day]. [month]. [year]")]
        }
        set figure(supplement: none, numbering: none)
        set image(height: 40%)
        set heading(outlined: false)
        doc
    }
}
