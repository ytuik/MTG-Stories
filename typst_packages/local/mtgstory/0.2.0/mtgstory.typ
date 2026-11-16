// Template de contos. Compilado para PDF (target "paged") e para HTML (conversor de EPUB).
// Tudo o que é específico de página fica condicionado a `context target() == "paged"`;
// o ramo HTML mantém a estrutura de antes (h3 do título, autor, set e data).
#import "themes.typ": theme-for as _theme-for, themes as _themes, set-themes as _set-themes

// Reexporta o tema por set (themes.typ é gerado por `python -m mtg_epub.typst_themes`).
#let theme-for = _theme-for
#let themes = _themes
#let set-themes = _set-themes

// ---------------------------------------------------------------------------------------------
// Estilo de livro (PDF)
// ---------------------------------------------------------------------------------------------

#let page-paper = "a4"
#let page-margin = (x: 3.2cm, top: 2.8cm, bottom: 2.8cm)

// Separador de cena: três losangos centralizados (desenhado, não depende de glifos da fonte).
#let scene-ornament(accent) = {
  v(0.9em, weak: true)
  align(center, stack(
    dir: ltr,
    spacing: 0.7em,
    ..range(3).map(_ => box(
      width: 0.45em,
      height: 0.45em,
      baseline: 0.1em,
      rotate(45deg, reflow: true, rect(width: 0.3em, height: 0.3em, fill: accent, stroke: none)),
    )),
  ))
  v(0.9em, weak: true)
}

// Cabeçalho discreto (cinza, versalete); some na página onde o conto começa.
#let story-header(title-left, title-right) = context {
  let here-page = here().page()
  if query(<story-title>).any(h => h.location().page() == here-page) {
    none
  } else {
    set text(size: 8pt, fill: luma(110))
    grid(
      columns: (1fr, 1fr),
      gutter: 1em,
      align(left, smallcaps(title-left)),
      align(right, smallcaps(title-right)),
    )
  }
}

#let page-footer() = context {
  set text(size: 9pt, fill: luma(60))
  align(center, counter(page).display("1"))
}

// Estilo comum de página, texto e parágrafos. Chame dentro de `context target() == "paged"`.
#let book-style(theme, header-left, header-right, body) = {
  set page(
    paper: page-paper,
    margin: page-margin,
    header: story-header(header-left, header-right),
    header-ascent: 35%,
    footer: page-footer(),
    footer-descent: 35%,
  )
  set text(font: theme.body-font, size: 10.5pt, lang: "en", hyphenate: true)
  set par(justify: true, leading: 0.65em, spacing: 0.65em, first-line-indent: 1.2em)
  set figure(supplement: none, numbering: none)
  show figure: set block(above: 1.1em, below: 1.1em)
  show figure.caption: set text(size: 8.5pt, style: "italic", fill: luma(90))
  show quote: set text(style: "italic")
  show line: it => if it.length == 100% { scene-ornament(theme.accent) } else { it }
  // Imagens nunca passam de ~60% da altura útil da página.
  show image: it => context layout(size => {
    let natural = measure(width: size.width, it)
    let limit = (page.height - page-margin.top - page-margin.bottom) * 0.6
    if natural.height > limit {
      align(center, scale(limit / natural.height * 100%, reflow: true, it))
    } else {
      it
    }
  })
  // Subtítulos internos dos contos (`=`, `==`): discretos, na cor do tema.
  show heading: it => block(
    above: 1.4em,
    below: 0.8em,
    sticky: true,
    text(font: theme.title-font, fill: theme.accent, size: 12pt, weight: "regular", it.body),
  )
  body
}

// ---------------------------------------------------------------------------------------------
// Capitular (drop cap) própria, sem pacotes externos
// ---------------------------------------------------------------------------------------------

#let _space = [ ].func()
#let _block-funcs = (parbreak, figure, heading, block, align, v, line, grid, table, list, enum, terms, pagebreak, pad, par)
#let _is-block(c) = c.func() in _block-funcs
#let _is-sep(c) = c.func() == _space or c.func() == parbreak

// Quebra os filhos de um parágrafo em "átomos" separados por espaços: o texto colado a elementos
// inline (aspas inteligentes, ênfase) forma um único átomo, para nunca cortar no meio de uma palavra.
// A primeira letra do parágrafo é removida (ela vira a capitular).
#let _atoms(children) = {
  let atoms = ()
  let cur = ()
  let first = true
  for c in children {
    if c.func() == text {
      let words = c.text.split(" ")
      for (idx, w) in words.enumerate() {
        let piece = w
        if first {
          piece = w.clusters().slice(1).join(default: "")
          first = false
        }
        if piece != "" { cur.push(piece) }
        if idx < words.len() - 1 {
          atoms.push(cur.join(default: "") + " ")
          cur = ()
        }
      }
    } else if c.func() == _space {
      atoms.push(cur.join(default: "") + " ")
      cur = ()
    } else {
      first = false
      cur.push(c)
    }
  }
  if cur.len() > 0 { atoms.push(cur.join()) }
  atoms
}

#let _dropcap(letter, atoms, theme, nlines: 3) = layout(size => context {
  let lead = par.leading.to-absolute()
  let edges = (top-edge: "cap-height", bottom-edge: "baseline")
  let one = measure(block(width: size.width)[x]).height
  let target = nlines * one + (nlines - 1) * lead
  let ref-size = 100pt
  let ratio = measure(text(font: theme.title-font, size: ref-size, ..edges)[#letter]).height / ref-size
  let big = target / ratio
  let glyph = text(font: theme.title-font, size: big, fill: theme.accent, ..edges)[#letter]
  let w = measure(glyph).width + 0.3em.to-absolute()
  let avail = size.width - w
  let limit = calc.min(atoms.len(), 70)
  let fits(k) = measure(block(width: avail, atoms.slice(0, k).join())).height <= target + 0.5pt
  // Maior prefixo de átomos que cabe em `nlines` linhas (busca binária).
  let lo = 0
  let hi = limit
  while lo < hi {
    let mid = calc.quo(lo + hi + 1, 2)
    if fits(mid) { lo = mid } else { hi = mid - 1 }
  }
  if lo == 0 {
    par(first-line-indent: 0pt)[#glyph#atoms.join()]
  } else {
    block(below: lead, grid(
      columns: (w, avail),
      column-gutter: 0pt,
      align(top + left, glyph),
      par(first-line-indent: 0pt, justify: true)[#atoms.slice(0, lo).join()#linebreak(justify: true)],
    ))
    if lo < atoms.len() {
      par(first-line-indent: 0pt)[#atoms.slice(lo).join()]
    }
  }
})

// Aplica a capitular ao primeiro parágrafo "de verdade" do conto (>= 100 caracteres, começando
// por uma letra). Rótulos curtos (< 30 caracteres, como "#strong[Helga]") são ignorados.
#let with-dropcap(doc, theme) = {
  if not doc.has("children") { return doc }
  let ch = doc.children
  let n = ch.len()
  let i = 0
  while i < n {
    while i < n and _is-sep(ch.at(i)) { i += 1 }
    if i >= n { break }
    let j = i
    let chars = 0
    while j < n and not _is-block(ch.at(j)) {
      if ch.at(j).func() == text { chars += ch.at(j).text.len() }
      j += 1
    }
    if chars >= 30 {
      let c = ch.at(i)
      if chars >= 100 and c.func() == text and c.text.first().match(regex("^\p{L}$")) != none {
        let letter = c.text.first()
        let atoms = _atoms(ch.slice(i, j))
        // O parágrafo seguinte vem depois de um bloco; devolve o recuo de primeira linha a ele.
        let after = ch.slice(j)
        let p = 0
        while p < after.len() and _is-sep(after.at(p)) { p += 1 }
        if p < after.len() and not _is-block(after.at(p)) {
          after = after.slice(0, p) + (h(1.2em),) + after.slice(p)
        }
        return [#ch.slice(0, i).join(default: none)#_dropcap(letter, atoms, theme)#after.join(default: none)]
      }
      break
    }
    i = calc.max(j, i + 1)
  }
  doc
}

// ---------------------------------------------------------------------------------------------
// conf
// ---------------------------------------------------------------------------------------------

#let story-title-block(theme, title, author, set_name, story_date) = {
  v(1.6cm)
  align(center)[
    #[#heading(level: 2, outlined: true, bookmarked: true, title)<story-title>]
    #v(0.6em)
    #text(size: 10pt, tracking: 0.08em)[#smallcaps(author)]
    #v(0.2em)
    #text(size: 9pt, style: "italic", fill: luma(100))[#set_name · #story_date.display("[day]. [month]. [year]")]
    #scene-ornament(theme.accent)
  ]
}

#let conf(
    title,
    set_name: "Unknown set",
    story_date: datetime(day: 05, month: 08, year: 1993),
    author: "Unknown author",
    doc
) = {
    let theme = theme-for(set_name)
    let with_images = sys.inputs.at("with_images", default: "true")
    show figure: it => if with_images == "true" { it }
    set document(title: title, author: author, date: story_date)
    context if target() == "paged" {
        pagebreak(weak: true)
        show: book-style.with(theme, title, set_name)
        {
            set par(justify: false)
            set text(hyphenate: false)
            show heading: it => align(center, block(
              width: 100%,
              text(font: theme.title-font, fill: theme.accent, size: 21pt, weight: "regular", it.body),
            ))
            story-title-block(theme, title, author, set_name, story_date)
        }
        set heading(outlined: false)
        with-dropcap(doc, theme)
    } else {
        {
            set text(size: 2.5em)
            set align(center)
            heading(level: 2, title)
            author
        }
        {
            set text(size: 1.5em)
            set align(center)
            [From set #emph[#set_name]\ #story_date.display("[day]. [month]. [year]")]
        }
        set heading(outlined: false)
        doc
    }
}

#let letter_block(body, border: false) = {
    block(
       width: 100%,
       inset: (
          top: 8pt,
          bottom: 16pt,
          right: 32pt,
          left: 32pt,
       ),
       stroke: if border { 1pt + black } else { none }
    )[#body]
}
