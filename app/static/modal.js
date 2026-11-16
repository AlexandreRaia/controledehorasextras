// Modal de cadastro e edicao (um <dialog id="modal"> por pagina).
// O htmx coloca o formulario em #modal-corpo; daqui o modal abre e fecha.
(function () {
  function modal() { return document.getElementById('modal'); }

  // O htmx dispara afterSwap no elemento que recebeu o conteudo (#modal-corpo),
  // e nao no link que foi clicado; por isso o ouvinte fica no documento.
  document.addEventListener('htmx:afterSwap', function (e) {
    var m = modal();
    if (m && e.target && e.target.id === 'modal-corpo' && !m.open) m.showModal();
  });

  // O servidor manda fechar depois de salvar (cabecalho HX-Trigger: modal-fechar).
  document.addEventListener('modal-fechar', function () {
    var m = modal();
    if (m && m.open) m.close();
  });

  // Formularios marcados com data-fecha-ao-sucesso fecham o modal quando o servidor
  // aceita a gravacao. Se o servidor devolve o erro no proprio modal (HX-Retarget),
  // ele continua aberto.
  document.addEventListener('htmx:afterRequest', function (e) {
    var m = modal(), d = e.detail;
    if (!m || !m.open || !d || !d.elt || !d.elt.hasAttribute('data-fecha-ao-sucesso')) return;
    if (d.successful && !d.xhr.getResponseHeader('HX-Retarget')) m.close();
  });

  // Clicar no fundo escuro, fora da caixa, tambem fecha.
  document.addEventListener('click', function (e) {
    if (e.target && e.target.id === 'modal') e.target.close();
  });
})();
