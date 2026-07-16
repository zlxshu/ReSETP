% -------------------------------------
% author      : latexstudio
% website     : www.latexstudio.net
% time        : 2022-06-15 18:12:55
% description : 系统工程理论与实践
% email       : typeset@latexstudio.net
% -------------------------------------

\NeedsTeXFormat{LaTeX2e}[1999/12/01]
\ProvidesClass{setp-new}[2022/06/15, v1.0 by latexstudio.net]

\DeclareOption*{\PassOptionsToClass{\CurrentOption}{ctexart}}
\ProcessOptions\relax
\LoadClass[fontset=none,a4paper,oneside,UTF8]{ctexart}
\RequirePackage{ifthen,ifpdf}

\newif\ifctexversion\ctexversionfalse

\ifpdf
  \RequirePackage{epstopdf}
  \ifthenelse{\lengthtest{\the\pdftexversion\pdftexrevision pt > 14012 pt}}{\ctexversionfalse}{\ctexversiontrue}
\else
  \RequirePackage{xeCJK}
  \ifthenelse{\lengthtest{\the\XeTeXversion\XeTeXrevision pt > 0.9997 pt}}{\ctexversionfalse}{\ctexversiontrue}
\fi

\ifctexversion
  \PassOptionsToClass{c5size}{ctexart}
\else
  \PassOptionsToClass{zihao={5}}{ctexart}
\fi

\RequirePackage{geometry}

\geometry{
  hmargin   = {22.5mm,22.5mm},
  vmargin   = {32.5mm,20mm},
  headsep   = 3mm,
  footskip  = 2mm,
}

\RequirePackage[small]{subfigure}
\RequirePackage[numbers,sort&compress,super,square]{natbib}

\RequirePackage{
  amsmath  , amsthm   , array    , bm       , booktabs ,
  caption  , enumitem , etoolbox , fancyhdr , graphicx ,
  makecell , multirow , pdfpages , tikz     , url      ,
  xcolor   , xparse   , xpatch   , enumitem , lscape , amssymb
}

\renewcommand\baselinestretch{1.24}\selectfont
\bibsep .7pt plus .4pt minus .4pt
\renewcommand{\bibfont}{\small}
\urlstyle{same}
% \bibhang 1em
\aboverulesep 1pt
\belowrulesep 1pt
\parskip 1pt
\setlist{nosep}
\allowdisplaybreaks

\def\proofname{证明}
\let\footnotesize\small
\def\c@cn@jol@name{系统工程理论与实践}
\def\c@en@jol@name{Systems Engineering --- Theory \& Practice}
\def\c@cn@abs@name{摘要}
\def\c@cn@key@name{关键词}
\def\c@en@abs@name{Abstract}
\def\c@en@key@name{Keywords}
% -- 命令初始化
\def\setp@year{2011}
\def\setp@month{1}
\def\setp@volume{54}
\def\setp@number{1}
\def\setp@paperdoi{}
\def\setp@clc{XXX}
\def\setp@dic{A}
\def\setp@paperid{}
\def\setp@documentcode{}
\def\setp@title{}
\def\setp@author{}
\def\setp@address{}
\def\setp@abstract{}
\def\setp@keywords{}
\def\setp@etitle{}
\def\setp@eauthor{}
\def\setp@eabstract{}
\def\setp@ekeywords{}
\def\setp@titlemark{}
\def\setp@citeauthor{}
\def\setp@citetitle{}
\def\setp@ecitetitle{}
\def\setp@eciteauthor{}

\def\m#1{\textsuperscript{\small #1}}
\newcommand\Volume[4]{\def\setp@year{#1}\def\setp@month{#2}\def\setp@volume{#3}\def\setp@number{#4}}
\newcommand\PageNum[1]{\setcounter{page}{#1}}
\newcommand\EditorNote[1]{%
  \begingroup
    \long\def\@makefntext##1{\renewcommand\baselinestretch{1}\selectfont \parindent 1em\noindent\hbox to 0pt{\hss$^{}$}##1}%
    \footnotetext{#1}%
  \endgroup}
\newcommand\PaperDOI[1]{\def\setp@paperdoi{#1}}
\newcommand\PaperID[1]{\def\setp@{#1}}
\newcommand\DocumentCode[1]{\def\setp@documentcode{#1}}
\newcommand\setp@enmonth[1]{%
  \ifcase#1\or Jan.\or Feb.\or Mar.\or Apr.\or May\or Jun.%
  \or Jul.\or Aug.\or Sep.\or Oct.\or Nov.\or Dec.\fi%
}
\newcommand\TitleMark[1]{\def\setp@titlemark{#1}}
\newcommand\Title[2][]{\global\def\setp@citetitle{#1}\def\setp@title{#2}
\ifx\setp@citetitle\empty
\global\def\setp@citetitle{\setp@title}
\fi
}
\newcommand\Author[2]{\def\setp@author{#1}\def\setp@address{#2}}
\newcommand\Abstract[1]{\def\setp@abstract{#1}}
\newcommand\Keywords[1]{\def\setp@keywords{#1}}
\newcommand\ETitle[2][]{\def\setp@ecitetitle{#1}\def\setp@etitle{#2}
\ifx\setp@ecitetitle\empty
\global\def\setp@ecitetitle{\setp@etitle}
\fi
}
\newcommand\EAuthor[2]{\def\setp@eauthor{#1}\def\setp@eaddress{#2}}
\newcommand\EAbstract[1]{\def\setp@eabstract{#1}}
\newcommand\EKeywords[1]{\def\setp@ekeywords{#1}}
\newcommand\jolname[2]{\def\c@cn@jol@name{#1}\def\c@en@jol@name{#2}}
\newcommand\Category[2]{\def\setp@clc{#1}\def\setp@dic{#2}}
\newcommand\tabnote[2][\linewidth]{\smallskip\par \parbox{#1}{\small #2}}
\newcommand\CiteAuthor[2]{
  \def\setp@citeauthor{#1}\def\setp@eciteauthor{#2}
  \EditorNote{\textbf{中文引用格式:} \setp@citeauthor\ \setp@citetitle[J].
   \c@cn@jol@name, \setp@year, \setp@volume(\setp@number): \thepage--\pageref{@LastPage}.
  }
  \EditorNote{\textbf{英文引用格式:}\ \setp@eciteauthor\ \setp@ecitetitle[J]. \c@en@jol@name, \setp@year, \setp@volume(\setp@number): \thepage--\pageref{@LastPage}.}
}

\DeclareCaptionLabelSeparator{halfem}{\enspace\enspace}



\captionsetup{
  font     = {small,bf},
  labelsep = halfem
}
\captionsetup[table]{
  position      = above,
  skip          = 0pt,
  justification = centerlast
}
\captionsetup[figure]{
  position      = below,
  skip          = 5pt,
  justification = centerlast
}

\def\ps@cjoeheadings{
  \def\@evenhead{%
    \vbox{%
      \vskip 2pt%
      \hbox to \textwidth {\hbox{\zihao{-5}第\,\setp@volume\,卷\ 第\,\setp@number\,期}\hfill\hbox{\zihao{-5}\c@cn@jol@name} \hfill
          \hbox{\zihao{-5} Vol.\,\setp@volume,\ No.\,\setp@number}}%
      \vskip 1.5mm%
      \hbox to \textwidth {\hbox{\zihao{-5}\setp@year\,年\,\setp@month\,月} \hfill \hbox{\small \c@en@jol@name} \hfill \hbox{\zihao{-5} \setp@enmonth{\setp@month},\ \setp@year}}%
      \vskip 1.5mm%
      \hrule width\textwidth height0.12 true mm\vskip0.85pt%
      \hrule width\textwidth height0.12 true mm\vskip0.85pt%
    }%
  }
  \let\@oddhead\@evenhead%
}

\fancypagestyle{main}{
  \fancyhf{}
  \fancyhead[R]{\zihao{-5}\ifodd\arabic{page}\relax\thepage\else 第\,\setp@volume\,卷\fi}
  \fancyhead[C]{\zihao{-5}\ifodd\arabic{page}\setp@titlemark\else\ziju{.3}\c@cn@jol@name \fi}
  \fancyhead[L]{\zihao{-5}\ifodd\arabic{page}第\,\setp@number\,期\else\thepage\fi}
}

\renewcommand\maketitle{%
  \pagestyle{main}
  \begingroup
  \parindent 0pt
  \thispagestyle{cjoeheadings}
    \begingroup
      \ifpdf
      \vspace*{-2pt}
      \else
      \vspace*{4pt}
      \fi
      \zihao{-5}\textbf{doi:}~\setp@paperdoi \hskip 4em
      中图法分类号:\ \ \setp@clc \hskip 4em
      文献标志码:\ \ \setp@dic
      \par
    \endgroup
  \vskip 1.1\baselineskip%
    \begingroup
      \centering%
      % -- 中文标题排版
      {\heiti\zihao{3}\setp@title\par}%
      \vskip .8\baselineskip%
      {\fangsong\zihao{4}\linespread{1.23}\selectfont \setp@author\par}%
      \vskip .3\baselineskip%
      {\fangsong\zihao{-5} \setp@address\par}
      \vskip .7\baselineskip%
      \begin{quote}
        \linespread{1.2}\selectfont
        {\heiti\ziju{1} \c@cn@abs@name}\quad \fangsong \setp@abstract\par%
        \vskip .2\baselineskip%
        {\heiti \c@cn@key@name}\quad \fangsong \setp@keywords
      \end{quote}%
      \smallskip
      % -- 英文标题排版
      {\bfseries\fontsize{14.35pt}{15pt}\selectfont\setp@etitle\par}%
      \vskip .8\baselineskip%
      {\small\linespread{1.23}\selectfont \setp@eauthor\par}%
      \vskip .2\baselineskip%
      {\fontsize{8pt}{10pt}\linespread{1.16}\selectfont \setp@eaddress\par}
      \vskip .7\baselineskip%
      \begin{quote}
        \fontsize{10pt}{12pt}\linespread{1.16}\selectfont
        {\bfseries \c@en@abs@name}\quad \setp@eabstract\par%
        \vskip .2\baselineskip%
        {\bfseries \c@en@key@name}\quad \setp@ekeywords\par%
      \end{quote}%
    \endgroup
  \endgroup
  \setcounter{footnote}{0}
  \renewcommand\thefootnote{\@arabic\c@footnote}
}

\ifctexversion
  \CTEXsetup[
    format     = \bfseries\zihao{-4},
    beforeskip = 1.5ex,
    afterskip  = 1ex plus .4pt minus .4pt,
    aftername  = \hskip .7em,
  ]{section}
  \CTEXsetup[
    format     = \bfseries,
    beforeskip = 1.5ex plus .4pt minus .4pt,
    afterskip  = 0.5ex plus .4pt minus .4pt,
    aftername  = \hskip .5em,
  ]{subsection}
  \CTEXsetup[
    format     = \bfseries,
    beforeskip = 1.5ex plus .4pt minus .4pt,
    afterskip  = 0.5ex plus .4pt minus .4pt,
    aftername  = \hskip .5em,
  ]{subsubsection}
  % \renewcommand\bibsection{%
  % \vspace*{1em}
  %  \section*{\centering\bfseries\zihao{-4}\ziju{1.7}\refname\@mkboth{\refname}{\refname}}%
  %  \vspace*{1em plus .4pt minus .4pt}
  % }%
  \@ifpackageloaded{xeCJK}{
    \punctstyle{banjiao}
    \CJKsetecglue{}
  }{}
\else
  \ctexset{
    section = {
      format     = \bfseries\zihao{-4},
      beforeskip = 1.5ex,
      afterskip  = 1ex plus .4pt minus .4pt,
      aftername  = \hskip .7em,
    },
    subsection = {
      format     = \bfseries,
      beforeskip = 1.5ex plus .4pt minus .4pt,
      afterskip  = 0.5ex plus .4pt minus .4pt,
      aftername  = \hskip .5em,
    },
    subsubsection = {
      format     = \bfseries,
      beforeskip = 1.5ex plus .4pt minus .4pt,
      afterskip  = 0.5ex plus .4pt minus .4pt,
      aftername  = \hskip .5em,
    },
  }
  \renewcommand\bibsection{%
    \vspace*{.3em}
    \section*{\refname\@mkboth{\refname}{\refname}}%
    \vspace*{0em plus .4pt minus .4pt}
  }%
  \@ifpackageloaded{xeCJK}{
    \xeCJKsetup{
      PunctStyle = banjiao,
     % CJKecglue  = {}
    }
  }{}
\fi

\AtBeginEnvironment{tabular}{\small }

\theoremstyle{definition}
\newtheoremstyle{mythm}{0ex}{0ex}
   {\songti}{\parindent}{\songti\bf }{}{1em}{}
\theoremstyle{mythm}%设置定理环境
\newtheorem{theorem}{定理\relax}
\newtheorem{lemma}{引理\relax}
\newtheorem{property}{性质\relax}
\newtheorem{proposition}{命题\relax}
\newtheorem{question}{问题\relax}
\newtheorem{corollary}{推论\relax}
\newtheorem{definition}{定义\relax}
\newtheorem{remark}{注\relax}
\newtheorem{example}{例\relax}
\renewenvironment{proof}[1][\proofname]{\par
  \pushQED{\qed}%
  \normalfont \topsep6\p@\@plus6\p@\relax
  \trivlist
  \item[\hskip\labelsep\bfseries #1]\ignorespaces
}{%
  \popQED\endtrivlist\@endpefalse
}

\newcommand*\Thanks[1]{\vskip8pt{\heiti\bf\relax 致谢}\hspace{0.25cm} #1\par}
\let\oldappendix\appendix
\def\appendix{\oldappendix \setcounter{page}{0} \pagenumbering{Roman}}
\let\oldendthebibliography\endthebibliography
\def\endthebibliography{\oldendthebibliography\label{@LastPage}}

\ifpdf
\else
  \RequirePackage[xetex]{hyperref}
  \hypersetup{
    hidelinks,
    CJKbookmarks       = true,
    bookmarksnumbered  = true,
    bookmarksopen      = true,
    bookmarksopenlevel = 2,
    unicode            = true,
    colorlinks         = false,
    breaklinks         = false,
  }
\fi

\endinput

%%
%% end setp-new.cls
