import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

// ==============================================================================
// CONFIGURAÇÃO CENTRAL DA API E SEGURANÇA
// ==============================================================================
class AppConfig {
  static const String baseUrl = 'https://barbearia-versati.onrender.com'; // Substitua pelo endereço do seu servidor
  static const String apiUrl = '$baseUrl/api';

  // O token NÃO fica mais no código: ele vem do login do admin (/api/admin/login)
  // e é guardado de forma criptografada no celular (Keystore/Keychain).
  static String adminToken = '';
  static const FlutterSecureStorage _storage = FlutterSecureStorage();
  static const String _chaveToken = 'versati_admin_token';

  static Future<void> carregarToken() async {
    try {
      adminToken = await _storage.read(key: _chaveToken) ?? '';
    } catch (_) {
      adminToken = '';
    }
  }

  static Future<void> salvarToken(String token) async {
    adminToken = token;
    await _storage.write(key: _chaveToken, value: token);
  }

  static Future<void> limparToken() async {
    adminToken = '';
    try {
      await _storage.delete(key: _chaveToken);
    } catch (_) {}
  }

  // Helper centralizado para injetar o token de segurança nas requisições admin/
  static Map<String, String> get adminHeaders => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $adminToken',
      };
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.carregarToken();
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Barbearia Versati - Admin',
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF000000),
        primaryColor: const Color(0xFFE5243B),
      ),
      home: const AuthScreen(),
    );
  }
}

// ==============================================================================
// TELA DE AUTENTICAÇÃO
// ==============================================================================

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  // Este app é só do administrador: não existe cadastro, apenas login.
  bool _obscureText = true;
  bool _isLoading = false;
  bool _verificandoSessao = true;

  final _emailController = TextEditingController();
  final _senhaController = TextEditingController();

  final Color _bgBlack = const Color(0xFF000000);
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _baseUrl = AppConfig.apiUrl;

  @override
  void initState() {
    super.initState();
    _verificarSessaoSalva();
  }

  /// Se já existe um token salvo e ele ainda vale no servidor, entra direto no painel.
  Future<void> _verificarSessaoSalva() async {
    if (AppConfig.adminToken.isNotEmpty) {
      try {
        final resp = await http
            .get(Uri.parse('$_baseUrl/admin/sessao'), headers: AppConfig.adminHeaders)
            .timeout(const Duration(seconds: 20));
        if (resp.statusCode == 200) {
          if (!mounted) return;
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (context) => const MainMultiTaskScreen()),
          );
          return;
        }
        if (resp.statusCode == 401) {
          await AppConfig.limparToken(); // token expirado ou inválido
        }
      } catch (_) {
        // sem conexão: mantém o token e mostra o login
      }
    }
    if (mounted) setState(() => _verificandoSessao = false);
  }

  Future<void> _submeterFormulario() async {
    final email = _emailController.text.trim();
    final senha = _senhaController.text;

    if (email.isEmpty || senha.isEmpty) {
      _mostrarMensagem('Preencha todos os campos!');
      return;
    }

    setState(() => _isLoading = true);

    final String endpoint = '$_baseUrl/admin/login';
    final Map<String, dynamic> payload = {'email': email, 'senha': senha};

    try {
      final response = await http.post(
        Uri.parse(endpoint),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(payload),
      );

      final resData = jsonDecode(response.body);
      if (!mounted) return;
      setState(() => _isLoading = false);

      if (response.statusCode == 200 && resData['sucesso'] == true && resData['token'] != null) {
        await AppConfig.salvarToken(resData['token'].toString());
        _senhaController.clear();
        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (context) => const MainMultiTaskScreen(),
          ),
        );
      } else {
        _mostrarMensagem(resData['mensagem'] ?? 'Ocorreu um erro.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarMensagem('Erro de conexão com o servidor.');
    }
  }

  void _mostrarMensagem(String texto) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(texto)),
    );
  }

  @override
  void dispose() {
    _emailController.dispose();
    _senhaController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_verificandoSessao) {
      return Scaffold(
        backgroundColor: _bgBlack,
        body: Center(child: CircularProgressIndicator(color: _brandRed)),
      );
    }
    return Scaffold(
      backgroundColor: _bgBlack,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24.0),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Image.asset(
                  'assets/logo_versati.jpeg',
                  height: 140,
                  fit: BoxFit.contain,
                  errorBuilder: (context, error, stackTrace) => const Icon(
                    Icons.content_cut,
                    size: 90,
                    color: Color(0xFFE5243B),
                  ),
                ),
                const SizedBox(height: 20),

                Container(
                  padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 20),
                  decoration: BoxDecoration(
                    color: _cardDark,
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Text(
                    'Painel Administrativo - Faça seu login',
                    style: TextStyle(
                      color: _textSecondary,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                const SizedBox(height: 20),

                TextField(
                  controller: _emailController,
                  style: const TextStyle(color: Colors.white),
                  decoration: _inputDecoration('E-mail do Admin', Icons.email_outlined),
                ),
                const SizedBox(height: 16),

                TextField(
                  controller: _senhaController,
                  obscureText: _obscureText,
                  style: const TextStyle(color: Colors.white),
                  decoration: _inputDecoration('Senha', Icons.lock_outline).copyWith(
                    suffixIcon: IconButton(
                      icon: Icon(
                        _obscureText ? Icons.visibility_off : Icons.visibility,
                        color: _textSecondary,
                      ),
                      onPressed: () => setState(() => _obscureText = !_obscureText),
                    ),
                  ),
                ),

                const SizedBox(height: 24),

                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: ElevatedButton(
                    onPressed: _isLoading ? null : _submeterFormulario,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _brandRed,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    child: _isLoading
                        ? const CircularProgressIndicator(color: Colors.white, strokeWidth: 2)
                        : Text(
                            'ENTRAR NO PAINEL',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                              letterSpacing: 1.2,
                            ),
                          ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration(String hint, IconData icon) {
    return InputDecoration(
      hintText: hint,
      hintStyle: TextStyle(color: _textSecondary, fontSize: 14),
      prefixIcon: Icon(icon, color: _textSecondary),
      filled: true,
      fillColor: _cardDark,
      contentPadding: const EdgeInsets.symmetric(vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide.none,
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: _brandRed, width: 1.5),
      ),
    );
  }
}

// ==============================================================================
// TELA MULTITAREFA PRINCIPAL DO ADM
// ==============================================================================

class MainMultiTaskScreen extends StatefulWidget {
  const MainMultiTaskScreen({super.key});

  @override
  State<MainMultiTaskScreen> createState() => _MainMultiTaskScreenState();
}

class _MainMultiTaskScreenState extends State<MainMultiTaskScreen> {
  int _currentIndex = 1;
  final GlobalKey<_FinanceiroViewState> _financeiroKey = GlobalKey<_FinanceiroViewState>();

  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);

  final List<String> _titulos = [
    'AGENDA DE ATENDIMENTOS',
    'PAINEL FINANCEIRO',
    'GERENCIAR',
    'CONFIGURAÇÕES',
  ];

  void _abrirModalGerenciar() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _cardDark,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext ctx) {
        return SafeArea(
          child: SingleChildScrollView(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        "GERENCIAR",
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 18,
                          fontWeight: FontWeight.bold,
                          letterSpacing: 1.1,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.grey),
                        onPressed: () => Navigator.pop(ctx),
                      ),
                    ],
                  ),
                  const Divider(color: Colors.white10),
                  const SizedBox(height: 10),

                  GridView.count(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    crossAxisCount: 3,
                    crossAxisSpacing: 12,
                    mainAxisSpacing: 12,
                    childAspectRatio: 1.0,
                    children: [
                      _buildItemMenu(ctx, Icons.content_cut, "Barbeiros", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarBarbeirosScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.calendar_month, "Agenda", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const AgendaProfissionalScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.history, "Histórico", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const HistoricoAtendimentosScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.payments_outlined, "Comissões", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const ComissoesScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.inventory_2_outlined, "Pacotes", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarPacotesScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.shopping_bag_outlined, "Produtos", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarProdutosScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.sell_outlined, "Preço Serviços", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarServicosScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.card_membership, "Assinaturas", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarAssinaturasScreen()),
                        );
                      }),
                      _buildItemMenu(ctx, Icons.workspace_premium_outlined, "Planos", () {
                        Navigator.pop(ctx);
                        Navigator.push(
                          context,
                          MaterialPageRoute(builder: (context) => const GerenciarPlanosScreen()),
                        );
                      }),
                    ],
                  )
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildItemMenu(BuildContext context, IconData icon, String label, VoidCallback onTap) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        decoration: BoxDecoration(
          color: const Color(0xFF000000),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, color: _brandRed, size: 28),
            const SizedBox(height: 8),
            Text(
              label,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 12,
                fontWeight: FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final List<Widget> paginas = [
      const AgendaProfissionalScreen(),        // 0: Agenda
      FinanceiroView(key: _financeiroKey),       // 1: Financeiro Integrado
      const SizedBox.shrink(),                   // 2: Gerenciar (Modal)
      const ConfiguracoesView(),                 // 3: Configuração
    ];

    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: _currentIndex == 0 ? null : AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: Text(
          _titulos[_currentIndex],
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.bold,
            letterSpacing: 1.1,
            fontSize: 18,
          ),
        ),
        actions: [
          if (_currentIndex == 1) ...[
            IconButton(
              icon: Icon(Icons.calendar_month, color: _brandRed),
              tooltip: 'Filtrar por Data',
              onPressed: () {
                _financeiroKey.currentState?.selecionarDataFiltro();
              },
            ),
            IconButton(
              icon: const Icon(Icons.refresh, color: Colors.white),
              tooltip: 'Atualizar Dados',
              onPressed: () {
                setState(() {});
                _financeiroKey.currentState?.carregarDados(manual: true);
              },
            ),
          ],
        ],
      ),

      body: IndexedStack(
        index: _currentIndex,
        children: paginas,
      ),

      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) {
          if (index == 2) {
            _abrirModalGerenciar();
          } else {
            setState(() {
              _currentIndex = index;
            });
            if (index == 1) {
              // ao entrar no Financeiro, atualiza a lista de barbeiros dos filtros
              _financeiroKey.currentState?._carregarBarbeirosFiltro();
            }
          }
        },
        backgroundColor: _cardDark,
        selectedItemColor: _brandRed,
        unselectedItemColor: const Color(0xFF8E8E93),
        type: BottomNavigationBarType.fixed,
        selectedFontSize: 11,
        unselectedFontSize: 11,
        items: const [
          BottomNavigationBarItem(
            icon: Icon(Icons.calendar_month_outlined),
            activeIcon: Icon(Icons.calendar_month),
            label: 'Agenda',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.attach_money_outlined),
            activeIcon: Icon(Icons.attach_money),
            label: 'Financeiro',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.tune_outlined),
            activeIcon: Icon(Icons.tune),
            label: 'Gerenciar',
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.settings_outlined),
            activeIcon: Icon(Icons.settings),
            label: 'Configuração',
          ),
        ],
      ),
    );
  }
}

// ==============================================================================
// TELA DE HISTÓRICO DE ATENDIMENTOS CONCLUÍDOS POR DATA
// ==============================================================================

class HistoricoAtendimentosScreen extends StatefulWidget {
  const HistoricoAtendimentosScreen({super.key});

  @override
  State<HistoricoAtendimentosScreen> createState() => _HistoricoAtendimentosScreenState();
}

class _HistoricoAtendimentosScreenState extends State<HistoricoAtendimentosScreen> {
  final Color _bgColor = const Color(0xFF121212);
  final Color _cardColor = const Color(0xFF1E1E1E);
  final Color _brandRed = const Color(0xFFCF243E);
  final Color _textSecondary = const Color(0xFF9E9E9E);

  List<dynamic> _historico = [];
  bool _isLoading = true;
  DateTime _dataSelecionada = DateTime.now();

  final String _apiUrlBase = '${AppConfig.apiUrl}/admin/dados';

  String get _apiUrl {
    final f =
        "${_dataSelecionada.year}-${_dataSelecionada.month.toString().padLeft(2, '0')}-${_dataSelecionada.day.toString().padLeft(2, '0')}";
    return '$_apiUrlBase?data=$f';
  }

  @override
  void initState() {
    super.initState();
    _carregarHistorico();
  }

  Future<void> _carregarHistorico() async {
    if (!mounted) return;
    setState(() => _isLoading = true);

    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (mounted) {
          setState(() {
            _historico = data['finalizados'] ?? [];
            _isLoading = false;
          });
        }
      } else {
        if (mounted) setState(() => _isLoading = false);
      }
    } catch (e) {
      debugPrint('Erro ao carregar histórico: $e');
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _selecionarData(BuildContext context) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: _dataSelecionada,
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(
              primary: _brandRed,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (picked != null && picked != _dataSelecionada) {
      setState(() {
        _dataSelecionada = picked;
      });
      _carregarHistorico();
    }
  }

  String _formatarDataExibicao(DateTime data) {
    return "${data.day.toString().padLeft(2, '0')}/${data.month.toString().padLeft(2, '0')}/${data.year}";
  }

  void _mostrarDetalhesAtendimento(Map<String, dynamic> item) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardColor,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: Row(
          children: [
            const Icon(Icons.check_circle, color: Colors.tealAccent, size: 22),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                'Detalhes do Atendimento',
                style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
              ),
            ),
          ],
        ),
        content: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _buildDetalheLinha('Cliente:', item['cliente_nome'] ?? 'Cliente'),
              _buildDetalheLinha('Telefone:', item['cliente_telefone'] ?? 'Não informado'),
              _buildDetalheLinha('Serviço:', item['servico'] ?? 'Corte'),
              _buildDetalheLinha('Profissional:', item['profissional'] ?? 'Profissional'),
              _buildDetalheLinha('Horário:', item['horario'] ?? '--:--'),
              _buildDetalheLinha('Data:', _formatarDataExibicao(_dataSelecionada)),
              _buildDetalheLinha('Forma de Pagamento:', item['tipo_pagamento'] ?? 'Presencial'),
              _buildDetalheLinha('Valor:', item['valor'] ?? 'R\$ 0,00', valorDestaque: true),
              const SizedBox(height: 8),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
                decoration: BoxDecoration(
                  color: Colors.teal.withOpacity(0.15),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.tealAccent.withOpacity(0.3)),
                ),
                child: const Text(
                  'STATUS: CONCLUÍDO',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: Colors.tealAccent, fontWeight: FontWeight.bold, fontSize: 12),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: Text('Fechar', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Widget _buildDetalheLinha(String label, String valor, {bool valorDestaque = false}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(
              label,
              style: TextStyle(color: _textSecondary, fontSize: 13, fontWeight: FontWeight.w500),
            ),
          ),
          Expanded(
            child: Text(
              valor,
              style: TextStyle(
                color: valorDestaque ? Colors.tealAccent : Colors.white,
                fontSize: 13,
                fontWeight: FontWeight.bold,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _cardColor,
        elevation: 0,
        title: const Text(
          'HISTÓRICO DE ATENDIMENTOS',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: Icon(Icons.calendar_month, color: _brandRed),
            tooltip: 'Selecionar Data',
            onPressed: () => _selecionarData(context),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70),
            tooltip: 'Atualizar',
            onPressed: _carregarHistorico,
          ),
        ],
      ),
      body: Column(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            color: _cardColor.withOpacity(0.4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.today, color: Colors.tealAccent, size: 16),
                const SizedBox(width: 8),
                Text(
                  'Data Selecionada: ${_formatarDataExibicao(_dataSelecionada)}',
                  style: const TextStyle(color: Colors.white70, fontWeight: FontWeight.bold, fontSize: 13),
                ),
              ],
            ),
          ),
          Expanded(
            child: _isLoading
                ? Center(child: CircularProgressIndicator(color: _brandRed))
                : _historico.isEmpty
                    ? Center(
                        child: Text(
                          'Nenhum atendimento concluído nesta data.',
                          style: TextStyle(color: _textSecondary, fontSize: 14),
                        ),
                      )
                    : RefreshIndicator(
                        onRefresh: _carregarHistorico,
                        color: _brandRed,
                        child: ListView.builder(
                          padding: const EdgeInsets.all(16),
                          itemCount: _historico.length,
                          itemBuilder: (context, index) {
                            final item = _historico[index];
                            return InkWell(
                              onTap: () => _mostrarDetalhesAtendimento(item),
                              borderRadius: BorderRadius.circular(12),
                              child: Container(
                                margin: const EdgeInsets.only(bottom: 12),
                                padding: const EdgeInsets.all(16),
                                decoration: BoxDecoration(
                                  color: _cardColor,
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(color: Colors.teal.withOpacity(0.3)),
                                ),
                                child: Row(
                                  children: [
                                    const Icon(Icons.check_circle, color: Colors.tealAccent, size: 22),
                                    const SizedBox(width: 12),
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            '${item['cliente_nome'] ?? 'Cliente'}',
                                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                          const SizedBox(height: 2),
                                          Text(
                                            'Serviço: ${item['servico'] ?? 'Corte'}',
                                            style: TextStyle(color: _textSecondary, fontSize: 12),
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                          const SizedBox(height: 2),
                                          Text(
                                            'Horário: ${item['horario'] ?? '--:--'} • Barbeiro: ${item['profissional'] ?? 'Profissional'}',
                                            style: const TextStyle(color: Colors.white54, fontSize: 11),
                                            maxLines: 1,
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                        ],
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      item['valor'] ?? 'R\$ 0,00',
                                      style: const TextStyle(color: Colors.tealAccent, fontWeight: FontWeight.bold, fontSize: 14),
                                    ),
                                  ],
                                ),
                              ),
                            );
                          },
                        ),
                      ),
          ),
        ],
      ),
    );
  }
}

// ==============================================================================
// TELA FINANCEIRO COM CARD DE DATA FIXADA E BOTÃO X PARA LIMPAR
// ==============================================================================

class FinanceiroView extends StatefulWidget {
  const FinanceiroView({super.key});

  @override
  State<FinanceiroView> createState() => _FinanceiroViewState();
}

class _FinanceiroViewState extends State<FinanceiroView> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  Map<String, dynamic> _dashboardData = {};
  List<dynamic> _finalizados = [];
  List<dynamic> _finalizadosSemanal = [];
  List<dynamic> _finalizadosMensal = [];
  List<dynamic> _servicosMaisSolicitados = [];
  double _valorTotalFinalizados = 0;
  bool _isLoading = true;
  Timer? _timerTempoReal;
  DateTime? _dataFiltro;

  // Filtro por barbeiro (null = todos)
  List<dynamic> _barbeirosFiltro = [];
  Set<String> _nomesExBarbeiros = {};
  String? _barbeiroSelecionado;

  final String _apiUrlBase = '${AppConfig.apiUrl}/admin/dados';

  // Datas independentes dos cards SEMANA e MÊS (null = acompanha o dia selecionado / hoje)
  DateTime? _dataSemana;
  DateTime? _dataMes;

  static const List<String> _mesesAbrev = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN', 'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ'];

  String _fmtApi(DateTime x) =>
      "${x.year}-${x.month.toString().padLeft(2, '0')}-${x.day.toString().padLeft(2, '0')}";

  String get _apiUrl {
    final params = <String, String>{
      't': DateTime.now().millisecondsSinceEpoch.toString(), // Garante que a URL muda e evita cache
    };
    if (_dataFiltro != null) params['data'] = _fmtApi(_dataFiltro!);
    if (_dataSemana != null) params['semana'] = _fmtApi(_dataSemana!);
    if (_dataMes != null) params['mes'] = _fmtApi(_dataMes!);
    return Uri.parse(_apiUrlBase).replace(queryParameters: params).toString();
  }

  // Segunda a domingo da semana de referência
  String get _intervaloSemana {
    final ref = _dataSemana ?? _dataFiltro ?? DateTime.now();
    final seg = DateTime(ref.year, ref.month, ref.day).subtract(Duration(days: ref.weekday - 1));
    final dom = seg.add(const Duration(days: 6));
    String dm(DateTime x) => "${x.day.toString().padLeft(2, '0')}/${x.month.toString().padLeft(2, '0')}";
    return '${dm(seg)} - ${dm(dom)}';
  }

  String get _rotuloSemana => _dataSemana == null ? 'SEMANA' : _intervaloSemana;

  String get _rotuloMes {
    if (_dataMes == null) return 'MÊS';
    return '${_mesesAbrev[_dataMes!.month - 1]}/${_dataMes!.year}';
  }

  String get _tituloDia => _dataFiltro == null
      ? 'Atendimentos de Hoje'
      : 'Atendimentos de ${_formatarDataCurta(_dataFiltro!)}';

  String get _intervaloMes {
    final ref = _dataMes ?? _dataFiltro ?? DateTime.now();
    return '${_mesesAbrev[ref.month - 1]}/${ref.year}';
  }

  String get _tituloSemana =>
      (_dataSemana == null && _dataFiltro == null) ? 'Atendimentos da Semana' : 'Semana $_intervaloSemana';

  String get _tituloMes {
    final ref = _dataMes ?? _dataFiltro;
    if (ref == null) return 'Atendimentos do Mês';
    return 'Mês de ${_mesesAbrev[ref.month - 1]}/${ref.year}';
  }

  Future<void> _selecionarSemana() async {
    final picked = await showDatePicker(
      context: context,
      initialDate: _dataSemana ?? _dataFiltro ?? DateTime.now(),
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      helpText: 'SELECIONE UM DIA DA SEMANA',
      builder: (context, child) => Theme(
        data: ThemeData.dark().copyWith(colorScheme: ColorScheme.dark(primary: _brandRed, onSurface: Colors.white)),
        child: child!,
      ),
    );
    if (picked != null) {
      setState(() => _dataSemana = picked);
      await carregarDados(manual: true);
    }
  }

  Future<void> _selecionarMes() async {
    final base = _dataMes ?? _dataFiltro ?? DateTime.now();
    int ano = base.year;
    final escolhido = await showDialog<DateTime>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          backgroundColor: _cardDark,
          title: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              IconButton(
                icon: const Icon(Icons.chevron_left, color: Colors.white),
                onPressed: ano > 2023 ? () => setD(() => ano--) : null,
              ),
              Text('$ano', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
              IconButton(
                icon: const Icon(Icons.chevron_right, color: Colors.white),
                onPressed: ano < 2030 ? () => setD(() => ano++) : null,
              ),
            ],
          ),
          content: SizedBox(
            width: 280,
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: List.generate(12, (i) {
                final sel = ano == base.year && i + 1 == base.month;
                return InkWell(
                  onTap: () => Navigator.pop(ctx, DateTime(ano, i + 1, 1)),
                  borderRadius: BorderRadius.circular(8),
                  child: Container(
                    width: 82,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    decoration: BoxDecoration(
                      color: sel ? _brandRed.withOpacity(0.25) : Colors.black,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: sel ? _brandRed : Colors.white10),
                    ),
                    child: Center(
                      child: Text(_mesesAbrev[i], style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13)),
                    ),
                  ),
                );
              }),
            ),
          ),
        ),
      ),
    );
    if (escolhido != null) {
      setState(() => _dataMes = escolhido);
      await carregarDados(manual: true);
    }
  }

  void _resetarSemanaMes() {
    if (_dataSemana == null && _dataMes == null) return;
    setState(() {
      _dataSemana = null;
      _dataMes = null;
    });
    carregarDados(manual: true);
  }

  @override
  void initState() {
    super.initState();
    _carregarBarbeirosFiltro();
    carregarDados(manual: true);
    _timerTempoReal = Timer.periodic(const Duration(seconds: 5), (_) {
      carregarDados(manual: false);
    });
  }

  @override
  void dispose() {
    _timerTempoReal?.cancel();
    super.dispose();
  }

  Future<void> carregarDados({bool manual = false}) async {
    if (manual && mounted) setState(() => _isLoading = true);
    _finalizados.clear();
    if (manual) await _carregarBarbeirosFiltro();
    try {
      final response = await http.get(Uri.parse(_apiUrl), headers: AppConfig.adminHeaders);
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (mounted) {
          setState(() {
            _dashboardData = data['dashboard'] ?? {};
            _finalizados = data['finalizados'] ?? [];
            _finalizadosSemanal = data['finalizados_semanal'] ?? [];
            _finalizadosMensal = data['finalizados_mensal'] ?? [];
            _servicosMaisSolicitados = data['servicos_mais_solicitados'] ?? [];
            _valorTotalFinalizados = double.tryParse('${data['valor_total_finalizados'] ?? 0}') ?? 0;
            _isLoading = false;
          });
        }
      } else {
        if (mounted && manual) setState(() => _isLoading = false);
      }
    } catch (e) {
      if (mounted && manual) setState(() => _isLoading = false);
    }
  }

  Future<void> _carregarBarbeirosFiltro() async {
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiUrl}/admin/barbeiros?incluir_inativos=1'),
        headers: AppConfig.adminHeaders,
      );
      if (resp.statusCode == 200 && mounted) {
        final todos = jsonDecode(resp.body)['barbeiros'] ?? [];
        bool _estaInativo(dynamic b) => b['ativo'] == 0 || b['ativo'] == false;
        // Só barbeiros cadastrados (ativos) aparecem no filtro do Financeiro.
        final lista = todos.where((b) => !_estaInativo(b)).toList();
        final nomesAtivos = lista.map((b) => (b['nome'] ?? '').toString().trim().toLowerCase()).toSet();
        setState(() {
          _barbeirosFiltro = lista;
          _nomesExBarbeiros = todos
              .where((b) => _estaInativo(b))
              .map((b) => (b['nome'] ?? '').toString().trim().toLowerCase())
              .where((n) => n.isNotEmpty && !nomesAtivos.contains(n))
              .cast<String>()
              .toSet();
          final nomes = lista.map((b) => (b['nome'] ?? '').toString()).toList();
          if (_barbeiroSelecionado != null && !nomes.contains(_barbeiroSelecionado)) {
            _barbeiroSelecionado = null;
          }
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar barbeiros do filtro: $e');
    }
  }

  bool _pertenceAoBarbeiro(dynamic item) {
    if (_barbeiroSelecionado == null) return true;
    final alvo = _barbeiroSelecionado!.trim().toLowerCase();
    final prof = (item['profissional'] ?? '').toString().trim().toLowerCase();
    return prof == alvo || prof.contains(alvo);
  }

  List<dynamic> _filtrar(List<dynamic> lista) =>
      _barbeiroSelecionado == null ? lista : lista.where(_pertenceAoBarbeiro).toList();

  double _valorDoItem(dynamic item) {
    final txt = (item['valor'] ?? '0')
        .toString()
        .replaceAll('R\$', '')
        .replaceAll(' ', '')
        .replaceAll('.', '')
        .replaceAll(',', '.');
    return double.tryParse(txt) ?? 0;
  }

  List<dynamic> get _finalizadosVisiveis => _filtrar(_finalizados);
  List<dynamic> get _semanalVisiveis => _filtrar(_finalizadosSemanal);
  List<dynamic> get _mensalVisiveis => _filtrar(_finalizadosMensal);

  double get _valorTotalExibido => _barbeiroSelecionado == null
      ? _valorTotalFinalizados
      : _finalizadosVisiveis.fold<double>(0, (soma, i) => soma + _valorDoItem(i));

  int _contagem(String chave, List<dynamic> visiveis) =>
      _barbeiroSelecionado == null ? (int.tryParse('${_dashboardData[chave] ?? 0}') ?? 0) : visiveis.length;

  List<dynamic> get _servicosExibidos {
    if (_barbeiroSelecionado == null) return _servicosMaisSolicitados;
    final Map<String, int> cont = {};
    for (final i in _finalizadosVisiveis) {
      final nome = (i['servico'] ?? 'Corte').toString();
      cont[nome] = (cont[nome] ?? 0) + 1;
    }
    final total = cont.values.fold<int>(0, (a, b) => a + b);
    final ordenado = cont.entries.toList()..sort((x, y) => y.value.compareTo(x.value));
    return ordenado
        .take(5)
        .map((e) => {
              'nome': e.key,
              'quantidade': e.value,
              'porcentagem': total == 0 ? 0.0 : double.parse((e.value / total).toStringAsFixed(2)),
            })
        .toList();
  }

  Widget _chipFiltroBarbeiro({required bool ativo, required Widget leading, required String label, required VoidCallback onTap}) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(24),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            color: ativo ? _brandRed.withOpacity(0.2) : _cardDark,
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: ativo ? _brandRed : Colors.white10),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              leading,
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(color: ativo ? Colors.white : _textSecondary, fontSize: 12, fontWeight: FontWeight.bold),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildFiltroBarbeiros() {
    if (_barbeirosFiltro.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: SizedBox(
        height: 42,
        child: ListView(
          scrollDirection: Axis.horizontal,
          children: [
            _chipFiltroBarbeiro(
              ativo: _barbeiroSelecionado == null,
              leading: Icon(Icons.groups, size: 18, color: _barbeiroSelecionado == null ? _brandRed : _textSecondary),
              label: 'Todos',
              onTap: () => setState(() => _barbeiroSelecionado = null),
            ),
            ..._barbeirosFiltro.map((b) {
              final nome = (b['nome'] ?? '').toString();
              return _chipFiltroBarbeiro(
                ativo: _barbeiroSelecionado == nome,
                leading: _buildAvatarBarbeiro(b['foto_url'], radius: 12),
                label: nome,
                onTap: () => setState(() => _barbeiroSelecionado = nome),
              );
            }),
          ],
        ),
      ),
    );
  }

  Future<void> selecionarDataFiltro() async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: _dataFiltro ?? DateTime.now(),
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(primary: _brandRed, onSurface: Colors.white),
          ),
          child: child!,
        );
      },
    );
    if (picked != null) {
      setState(() {
        _dataFiltro = picked;
        _dataSemana = null;
        _dataMes = null;
      });
      carregarDados(manual: true);
    }
  }

  void _limparFiltroData() {
    setState(() {
      _dataFiltro = null;
      _dataSemana = null;
      _dataMes = null;
    });
    carregarDados(manual: true);
  }

  String _formatarDataCurta(DateTime d) {
    return "${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}/${d.year}";
  }

  // Card pequeno e visível dentro do painel para escolher a data da semana ou do mês
  Widget _seletorPeriodoSheet(String tipo, StateSetter setSheet) {
    final bool semana = tipo == 'semana';
    final bool personalizado = semana ? _dataSemana != null : _dataMes != null;
    final String rotulo = semana ? 'Semana: $_intervaloSemana' : 'Mês: $_intervaloMes';

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: _brandRed.withOpacity(0.12),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: _brandRed.withOpacity(personalizado ? 0.8 : 0.4)),
      ),
      child: Row(
        children: [
          Icon(semana ? Icons.calendar_view_week : Icons.calendar_month, color: _brandRed, size: 16),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              rotulo,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
            ),
          ),
          if (personalizado)
            InkWell(
              onTap: () async {
                setState(() {
                  if (semana) {
                    _dataSemana = null;
                  } else {
                    _dataMes = null;
                  }
                });
                await carregarDados(manual: true);
                setSheet(() {});
              },
              borderRadius: BorderRadius.circular(20),
              child: Container(
                padding: const EdgeInsets.all(5),
                margin: const EdgeInsets.only(right: 6),
                decoration: BoxDecoration(color: Colors.white.withOpacity(0.08), shape: BoxShape.circle),
                child: const Icon(Icons.restart_alt, color: Colors.white70, size: 16),
              ),
            ),
          InkWell(
            onTap: () async {
              if (semana) {
                await _selecionarSemana();
              } else {
                await _selecionarMes();
              }
              setSheet(() {});
            },
            borderRadius: BorderRadius.circular(8),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(color: _brandRed, borderRadius: BorderRadius.circular(8)),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: const [
                  Icon(Icons.edit_calendar, color: Colors.white, size: 14),
                  SizedBox(width: 4),
                  Text('Alterar', style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // tipo: 'dia' | 'semana' | 'mes'
  void _mostrarListaPeriodo(String tipo) {
    showModalBottomSheet(
      context: context,
      backgroundColor: _cardDark,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return StatefulBuilder(builder: (context, setSheet) {
        final String titulo = tipo == 'semana' ? _tituloSemana : (tipo == 'mes' ? _tituloMes : _tituloDia);
        final List<dynamic> lista = tipo == 'semana' ? _semanalVisiveis : (tipo == 'mes' ? _mensalVisiveis : _finalizadosVisiveis);
        return DraggableScrollableSheet(
          initialChildSize: 0.85,
          minChildSize: 0.5,
          maxChildSize: 0.95,
          expand: false,
          builder: (_, controller) {
            return Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 40,
                      height: 4,
                      decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(2)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Text(
                          titulo,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '${lista.length} atendimento(s)',
                        style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 13),
                      ),
                    ],
                  ),
                  const Divider(color: Colors.white10, height: 20),
                  if (tipo != 'dia') _seletorPeriodoSheet(tipo, setSheet),
                  Expanded(
                    child: lista.isEmpty
                        ? Center(
                            child: Text(
                              'Nenhum atendimento registrado neste período.',
                              style: TextStyle(color: _textSecondary, fontSize: 13),
                            ),
                          )
                        : ListView.builder(
                            controller: controller,
                            itemCount: lista.length,
                            itemBuilder: (context, index) {
                              final item = lista[index];
                              return Container(
                                margin: const EdgeInsets.only(bottom: 10),
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: Colors.black,
                                  borderRadius: BorderRadius.circular(10),
                                  border: Border.all(color: Colors.white10),
                                ),
                                child: Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Expanded(
                                      child: Column(
                                        crossAxisAlignment: CrossAxisAlignment.start,
                                        children: [
                                          Text(
                                            '${item['cliente_nome'] ?? 'Cliente'} - ${item['servico'] ?? 'Corte'}',
                                            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                                            overflow: TextOverflow.ellipsis,
                                          ),
                                          const SizedBox(height: 4),
                                          Text(
                                            'Data: ${item['data'] ?? '--/--'} • Hora: ${item['horario'] ?? '--:--'} • Barbeiro: ${item['profissional'] ?? ''}',
                                            style: TextStyle(color: _textSecondary, fontSize: 11),
                                          ),
                                        ],
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Text(
                                      item['valor'] ?? 'R\$ 0,00',
                                      style: const TextStyle(color: Colors.greenAccent, fontWeight: FontWeight.bold, fontSize: 13),
                                    ),
                                  ],
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
            );
          },
        );
        });
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return _isLoading
        ? Center(child: CircularProgressIndicator(color: _brandRed))
        : RefreshIndicator(
            onRefresh: () => carregarDados(manual: true),
            color: _brandRed,
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Card indicador de Data Fixada com botão X para limpar
                  if (_dataFiltro != null) ...[
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: _brandRed.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: _brandRed.withOpacity(0.4)),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.push_pin, color: _brandRed, size: 16),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Data fixada: ${_formatarDataCurta(_dataFiltro!)}',
                              style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
                            ),
                          ),
                          InkWell(
                            onTap: _limparFiltroData,
                            borderRadius: BorderRadius.circular(20),
                            child: Container(
                              padding: const EdgeInsets.all(4),
                              decoration: BoxDecoration(
                                color: Colors.white.withOpacity(0.08),
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(Icons.close, color: Colors.white70, size: 16),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  _buildFiltroBarbeiros(),

                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: LinearGradient(
                        colors: [_brandRed.withOpacity(0.25), _cardDark],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: _brandRed.withOpacity(0.3)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(Icons.check_circle_outline, color: Colors.greenAccent, size: 16),
                            const SizedBox(width: 6),
                            Text('VALOR TOTAL EM CORTES FINALIZADOS', style: TextStyle(color: _textSecondary, fontSize: 11, fontWeight: FontWeight.bold)),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'R\$ ${_valorTotalExibido.toStringAsFixed(2).replaceAll('.', ',')}',
                          style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  Row(
                    children: [
                      _buildClickableMetricCard(_dataFiltro == null ? 'HOJE' : 'DIA ${_formatarDataCurta(_dataFiltro!).substring(0, 5)}', '${_contagem('diario', _finalizadosVisiveis)} Cortes', Icons.today, () {
                        _mostrarListaPeriodo('dia');
                      }),
                      const SizedBox(width: 8),
                      _buildClickableMetricCard(_rotuloSemana, '${_contagem('semanal', _semanalVisiveis)} Cortes', Icons.calendar_view_week, () {
                        _mostrarListaPeriodo('semana');
                      }, onPickDate: _selecionarSemana, onResetDate: _resetarSemanaMes, personalizado: _dataSemana != null),
                      const SizedBox(width: 8),
                      _buildClickableMetricCard(_rotuloMes, '${_contagem('mensal', _mensalVisiveis)} Cortes', Icons.calendar_month, () {
                        _mostrarListaPeriodo('mes');
                      }, onPickDate: _selecionarMes, onResetDate: _resetarSemanaMes, personalizado: _dataMes != null),
                    ],
                  ),
                  const SizedBox(height: 24),


                  const Text('Serviços Mais Solicitados', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(color: _cardDark, borderRadius: BorderRadius.circular(16), border: Border.all(color: Colors.white10)),
                    child: _servicosExibidos.isEmpty
                        ? Padding(
                            padding: const EdgeInsets.symmetric(vertical: 8),
                            child: Text('Nenhum agendamento registrado ainda.', style: TextStyle(color: _textSecondary, fontSize: 12)),
                          )
                        : Column(children: _servicosExibidos.map((c) => _buildCorteMaisVendidoRow(Map<String, dynamic>.from(c))).toList()),
                  ),
                  const SizedBox(height: 24),

                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text(
                        'Cortes Finalizados',
                        style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold),
                      ),
                      Text(
                        '${_finalizadosVisiveis.length} concluídos',
                        style: const TextStyle(color: Colors.greenAccent, fontSize: 12),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  if (_finalizadosVisiveis.isEmpty)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        color: _cardDark,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Center(
                        child: Text(
                          'Nenhum corte finalizado registrado.',
                          style: TextStyle(color: _textSecondary),
                        ),
                      ),
                    )
                  else
                    ListView.builder(
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      itemCount: _finalizadosVisiveis.length,
                      itemBuilder: (context, index) {
                        final item = _finalizadosVisiveis[index];
                        return _buildFinalizadoTile(item);
                      },
                    ),
                ],
              ),
            ),
          );
  }

  Widget _buildClickableMetricCard(
    String title,
    String value,
    IconData icon,
    VoidCallback onTap, {
    VoidCallback? onPickDate,
    VoidCallback? onResetDate,
    bool personalizado = false,
  }) {
    return Expanded(
      child: Stack(
        children: [
          InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(12),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
              decoration: BoxDecoration(
                color: _cardDark,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: personalizado ? _brandRed : _brandRed.withOpacity(0.3)),
              ),
              child: Column(
                children: [
                  Icon(icon, color: _brandRed, size: 20),
                  const SizedBox(height: 6),
                  Text(value, style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 2),
                  Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(color: personalizado ? Colors.white : _textSecondary, fontSize: 10, fontWeight: FontWeight.w600),
                  ),
                ],
              ),
            ),
          ),
          if (onPickDate != null)
            Positioned(
              top: 4,
              right: 4,
              child: Tooltip(
                message: 'Escolher data (segure para voltar ao padrão)',
                child: InkWell(
                  onTap: onPickDate,
                  onLongPress: onResetDate,
                  borderRadius: BorderRadius.circular(12),
                  child: Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: personalizado ? _brandRed.withOpacity(0.25) : Colors.white.withOpacity(0.06),
                      shape: BoxShape.circle,
                    ),
                    child: Icon(Icons.edit_calendar, size: 13, color: personalizado ? Colors.white : _textSecondary),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildCorteMaisVendidoRow(Map<String, dynamic> c) {
    final double porcentagem = double.tryParse('${c['porcentagem'] ?? 0}') ?? 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(child: Text(c['nome'] ?? '', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13))),
              Text('${c['quantidade']}x (${(porcentagem * 100).toStringAsFixed(0)}%)', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 12)),
            ],
          ),
          const SizedBox(height: 6),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(
              value: porcentagem,
              backgroundColor: Colors.black,
              valueColor: AlwaysStoppedAnimation<Color>(_brandRed),
              minHeight: 6,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFinalizadoTile(Map<String, dynamic> item) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _cardDark,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.green.withOpacity(0.2)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Row(
              children: [
                const Icon(Icons.check_circle_outline, color: Colors.greenAccent, size: 22),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${item['cliente_nome'] ?? 'Cliente'} - ${item['servico'] ?? 'Corte'}',
                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${item['horario'] ?? '--:--'} • Barbeiro: ${item['profissional'] ?? 'Atendente'}',
                        style: const TextStyle(color: Colors.white54, fontSize: 11),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            item['valor'] ?? 'R\$ 35,00',
            style: const TextStyle(color: Colors.greenAccent, fontWeight: FontWeight.bold, fontSize: 14),
          ),
        ],
      ),
    );
  }
}

// ==============================================================================
// CONFIGURAÇÕES E DADOS DA BARBEARIA
// ==============================================================================

class ConfiguracoesView extends StatelessWidget {
  const ConfiguracoesView({super.key});

  @override
  Widget build(BuildContext context) {
    final Color cardDark = const Color(0xFF121212);
    final Color brandRed = const Color(0xFFE5243B);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        ListTile(
          tileColor: cardDark,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          leading: const Icon(Icons.history, color: Colors.white),
          title: const Text('Histórico de Atendimentos', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          subtitle: const Text('Localizar agendamentos concluídos por data', style: TextStyle(color: Colors.white54, fontSize: 12)),
          trailing: const Icon(Icons.arrow_forward_ios, size: 16, color: Colors.white54),
          onTap: () {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => const HistoricoAtendimentosScreen()),
            );
          },
        ),
        const SizedBox(height: 12),
        ListTile(
          tileColor: cardDark,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          leading: const Icon(Icons.people_alt_outlined, color: Colors.white),
          title: const Text('Usuários Cadastrados', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          subtitle: const Text('Ver e-mails e redefinir senhas de clientes', style: TextStyle(color: Colors.white54, fontSize: 12)),
          trailing: const Icon(Icons.arrow_forward_ios, size: 16, color: Colors.white54),
          onTap: () {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => const GerenciarUsuariosScreen()),
            );
          },
        ),
        const SizedBox(height: 12),
        ListTile(
          tileColor: cardDark,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          leading: const Icon(Icons.storefront_outlined, color: Colors.white),
          title: const Text('Dados da Barbearia', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          subtitle: const Text('Endereço, horários e contatos', style: TextStyle(color: Colors.white54, fontSize: 12)),
          trailing: const Icon(Icons.arrow_forward_ios, size: 16, color: Colors.white54),
          onTap: () {
            Navigator.push(
              context,
              MaterialPageRoute(builder: (context) => const DadosBarbeariaScreen()),
            );
          },
        ),
        const SizedBox(height: 12),
        ListTile(
          tileColor: cardDark,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          leading: Icon(Icons.exit_to_app, color: brandRed),
          title: Text('Sair da Conta', style: TextStyle(color: brandRed, fontWeight: FontWeight.bold)),
          onTap: () async {
            final navigator = Navigator.of(context);
            await AppConfig.limparToken();
            navigator.pushReplacement(
              MaterialPageRoute(builder: (context) => const AuthScreen()),
            );
          },
        ),
      ],
    );
  }
}

class DadosBarbeariaScreen extends StatelessWidget {
  const DadosBarbeariaScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final Color bgBlack = const Color(0xFF000000);
    final Color cardDark = const Color(0xFF121212);
    final Color brandRed = const Color(0xFFE5243B);
    final Color textSecondary = const Color(0xFF8E8E93);

    return Scaffold(
      backgroundColor: bgBlack,
      appBar: AppBar(
        backgroundColor: cardDark,
        elevation: 0,
        title: const Text(
          'DADOS DA BARBEARIA',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(20),
              decoration: BoxDecoration(
                color: cardDark,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white10),
              ),
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 30,
                    backgroundColor: brandRed.withOpacity(0.2),
                    child: Icon(Icons.content_cut, color: brandRed, size: 30),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Barbearia Versati',
                          style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Estilo, tradição e precisão no seu corte.',
                          style: TextStyle(color: textSecondary, fontSize: 13),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            _buildSectionHeader('Informações Gerais'),
            const SizedBox(height: 10),
            _buildInfoTile(
              cardDark,
              Icons.location_on_outlined,
              'Endereço',
              'Rua Creusa Campos de Vasconcelos, 102, João Pessoa, PB',
              brandRed,
            ),
            const SizedBox(height: 10),
            _buildInfoTile(
              cardDark,
              Icons.phone_outlined,
              'Telefone / WhatsApp',
              '(83) 98642-9833',
              brandRed,
            ),
            const SizedBox(height: 10),
            _buildInfoTile(
              cardDark,
              Icons.access_time_outlined,
              'Horário de Funcionamento',
              'Segunda a Sábado: 09:00 - 19:00',
              brandRed,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Text(
      title,
      style: const TextStyle(
        color: Colors.white,
        fontSize: 16,
        fontWeight: FontWeight.bold,
      ),
    );
  }

  Widget _buildInfoTile(Color bg, IconData icon, String title, String value, Color iconColor) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Row(
        children: [
          Icon(icon, color: iconColor, size: 22),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(color: Colors.white54, fontSize: 12),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// ==============================================================================
// TELA DE GERENCIAR USUÁRIOS
// ==============================================================================

class GerenciarUsuariosScreen extends StatefulWidget {
  const GerenciarUsuariosScreen({super.key});

  @override
  State<GerenciarUsuariosScreen> createState() => _GerenciarUsuariosScreenState();
}

class _GerenciarUsuariosScreenState extends State<GerenciarUsuariosScreen> {
  final Color _bgBlack = const Color(0xFF000000);
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  List<dynamic> _usuarios = [];
  bool _isLoading = true;

  final String _apiUrl = '${AppConfig.apiUrl}/admin/usuarios';

  @override
  void initState() {
    super.initState();
    _carregarUsuarios();
  }

  Future<void> _carregarUsuarios() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _usuarios = data['usuarios'] ?? [];
          _isLoading = false;
        });
      } else {
        _mostrarSnack('Erro ao carregar lista de usuários.');
        setState(() => _isLoading = false);
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
      setState(() => _isLoading = false);
    }
  }

  Future<void> _resetarSenhaAPI(int usuarioId, String novaSenha) async {
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiUrl}/admin/resetar-senha'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'usuario_id': usuarioId,
          'nova_senha': novaSenha,
        }),
      );

      final resData = jsonDecode(response.body);

      if (!mounted) return;
      if (response.statusCode == 200 && resData['sucesso'] == true) {
        _mostrarSnack('✅ Senha alterada com sucesso!');
        _carregarUsuarios();
      } else {
        _mostrarSnack('❌ Erro: ${resData['mensagem'] ?? 'Falha ao alterar.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão ao alterar senha.');
    }
  }

  Future<void> _removerUsuarioAPI(int usuarioId) async {
    try {
      final response = await http.delete(
        Uri.parse('$_apiUrl/$usuarioId'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('🗑️ Usuário e registros vinculados removidos!');
        _carregarUsuarios();
      } else {
        final resData = jsonDecode(response.body);
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Erro ao remover usuário.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _mostrarSenhaModal(int usuarioId, String nomeUsuario) async {
    try {
      final response = await http.get(
        Uri.parse('${AppConfig.apiUrl}/admin/usuario/$usuarioId/senha'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;

      Map<String, dynamic> data = {};
      try {
        data = jsonDecode(response.body);
      } catch (_) {}

      if (response.statusCode == 200 && data['sucesso'] == true) {
        final senhaRetornada = (data['senha'] ?? '').toString();
        showDialog(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: _cardDark,
            title: Text('Senha de $nomeUsuario', style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Senha registrada:', style: TextStyle(color: _textSecondary, fontSize: 12)),
                const SizedBox(height: 8),
                SelectableText(
                  senhaRetornada,
                  style: const TextStyle(color: Colors.greenAccent, fontSize: 18, fontWeight: FontWeight.w700),
                ),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: senhaRetornada));
                  _mostrarSnack('Senha copiada.');
                },
                child: const Text('Copiar', style: TextStyle(color: Colors.white70)),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: Text('Fechar', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        );
      } else {
        // mostra o motivo que o servidor informou (ex.: senha ainda não disponível)
        _mostrarSnack((data['mensagem'] ?? 'Erro ao buscar senha.').toString());
      }
    } catch (e) {
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _exibirDialogoResetarSenha(int usuarioId, String nomeUsuario) {
    final TextEditingController senhaController = TextEditingController();

    showDialog(
      context: context,
      builder: (context) {
        return AlertDialog(
          backgroundColor: _cardDark,
          title: const Text(
            'REDEFINIR SENHA DO CLIENTE',
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Digite a nova senha para $nomeUsuario:',
                style: TextStyle(color: _textSecondary, fontSize: 13),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: senhaController,
                obscureText: true,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  hintText: 'Mínimo 8 caracteres',
                  hintStyle: TextStyle(color: _textSecondary.withOpacity(0.5), fontSize: 12),
                  filled: true,
                  fillColor: Colors.black,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: const BorderSide(color: Colors.white24),
                  ),
                  focusedBorder: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(8),
                    borderSide: BorderSide(color: _brandRed),
                  ),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
              onPressed: () {
                final novaSenha = senhaController.text.trim();
                if (novaSenha.isEmpty) {
                  _mostrarSnack('Informe a nova senha.');
                  return;
                }
                if (novaSenha.length < 8) {
                  _mostrarSnack('A senha deve ter pelo menos 8 caracteres.');
                  return;
                }
                Navigator.pop(context);
                _resetarSenhaAPI(usuarioId, novaSenha);
              },
              child: const Text('Salvar', style: TextStyle(color: Colors.white)),
            ),
          ],
        );
      },
    );
  }

  void _confirmarRemocao(int usuarioId, String nomeUsuario) {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: _cardDark,
        title: const Text(
          'REMOVER USUÁRIO',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
        ),
        content: Text(
          'Deseja realmente remover o usuário $nomeUsuario? Todos os agendamentos vinculados também serão removidos.',
          style: TextStyle(color: _textSecondary, fontSize: 13),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
            onPressed: () {
              Navigator.pop(context);
              _removerUsuarioAPI(usuarioId);
            },
            child: const Text('Remover', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }
  void _abrirDialogoCadastrarUsuario() {
    final nomeCtrl = TextEditingController();
    final emailCtrl = TextEditingController();
    final senhaCtrl = TextEditingController();
    final telefoneCtrl = TextEditingController();

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardDark,
        title: const Text(
          'CADASTRAR NOVO USUÁRIO',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nomeCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Nome Completo',
                  labelStyle: TextStyle(color: Colors.grey),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: emailCtrl,
                keyboardType: TextInputType.emailAddress,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'E-mail',
                  labelStyle: TextStyle(color: Colors.grey),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: senhaCtrl,
                obscureText: true,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Senha (mín. 8 caracteres)',
                  labelStyle: TextStyle(color: Colors.grey),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: telefoneCtrl,
                keyboardType: TextInputType.phone,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Telefone',
                  labelStyle: TextStyle(color: Colors.grey),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
            onPressed: () async {
              final nome = nomeCtrl.text.trim();
              final email = emailCtrl.text.trim();
              final senha = senhaCtrl.text.trim();
              final telefone = telefoneCtrl.text.trim();

              if (nome.isEmpty || email.isEmpty || senha.isEmpty) {
                _mostrarSnack('Preencha os campos obrigatórios!');
                return;
              }
              Navigator.pop(ctx);

              try {
                final response = await http.post(
                  Uri.parse('${AppConfig.apiUrl}/admin/usuarios'),
                  headers: AppConfig.adminHeaders,
                  body: jsonEncode({
                    'nome': nome,
                    'email': email,
                    'senha': senha,
                    'telefone': telefone,
                  }),
                );
                final resData = jsonDecode(response.body);
                if (!mounted) return;

                if ((response.statusCode == 200 || response.statusCode == 201) && resData['sucesso'] == true) {
                  _mostrarSnack('✅ Usuário cadastrado com sucesso!');
                  _carregarUsuarios();
                } else {
                  _mostrarSnack('❌ ${resData['mensagem'] ?? 'Erro ao cadastrar.'}');
                }
              } catch (e) {
                if (!mounted) return;
                _mostrarSnack('Erro de conexão com o servidor.');
              }
            },
            child: const Text('Cadastrar', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgBlack,
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text(
          'USUÁRIOS CADASTRADOS',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
        actions: [
          // Botão para cadastrar novo usuário pedindo todos os dados
          IconButton(
            icon: const Icon(Icons.person_add, color: Colors.white),
            tooltip: 'Cadastrar Novo Usuário',
            onPressed: _abrirDialogoCadastrarUsuario,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white),
            onPressed: _carregarUsuarios,
          ),
        ],
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _usuarios.isEmpty
              ? Center(
                  child: Text(
                    'Nenhum usuário cadastrado.',
                    style: TextStyle(color: _textSecondary),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _carregarUsuarios,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _usuarios.length,
                    itemBuilder: (context, index) {
                      final u = _usuarios[index];
                      return _buildUsuarioCard(u);
                    },
                  ),
                ),
    );
  }

  Widget _buildUsuarioCard(Map<String, dynamic> u) {
    final int id = u['id'];

    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _cardDark,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                backgroundColor: _brandRed.withOpacity(0.2),
                child: Icon(Icons.person, color: _brandRed),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  u['nome'] ?? 'Sem Nome',
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                    fontSize: 16,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                'ID: #$id',
                style: TextStyle(color: _textSecondary, fontSize: 12),
              ),
              const SizedBox(width: 8),
              IconButton(
                icon: const Icon(Icons.delete_outline, color: Colors.white38, size: 20),
                tooltip: 'Remover Usuário',
                onPressed: () => _confirmarRemocao(id, u['nome'] ?? 'Cliente'),
              ),
            ],
          ),
          const Divider(color: Colors.white10, height: 20),
          Row(
            children: [
              Icon(Icons.email_outlined, size: 16, color: _textSecondary),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  u['email'] ?? 'Sem e-mail',
                  style: const TextStyle(color: Colors.white70, fontSize: 14),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              // Botão VER SENHA
              InkWell(
                onTap: () => _mostrarSenhaModal(id, u['nome'] ?? 'Cliente'),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.blue.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.blueAccent, width: 0.8),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.visibility, color: Colors.blueAccent, size: 14),
                      SizedBox(width: 4),
                      Text(
                        'VER SENHA',
                        style: TextStyle(color: Colors.blueAccent, fontSize: 10, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ),
              ),
              // Botão ALTERAR
              InkWell(
                onTap: () => _exibirDialogoResetarSenha(
                  id,
                  u['nome'] ?? 'Cliente',
                ),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: Colors.orange.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.orange, width: 0.8),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.edit, color: Colors.orangeAccent, size: 14),
                      SizedBox(width: 4),
                      Text(
                        'ALTERAR',
                        style: TextStyle(color: Colors.orangeAccent, fontSize: 10, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class GerenciarProdutosScreen extends StatefulWidget {
  const GerenciarProdutosScreen({super.key});

  @override
  State<GerenciarProdutosScreen> createState() => _GerenciarProdutosScreenState();
}

class _GerenciarProdutosScreenState extends State<GerenciarProdutosScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _apiUrl = '${AppConfig.apiUrl}/admin/produtos';

  List<dynamic> _produtos = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _carregarProdutos();
  }

  Future<void> _carregarProdutos() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _produtos = data['produtos'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar produtos.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _cadastrarProdutoAPI(String nome, String descricao, double preco, int estoque, String foto) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome, 
          'descricao': descricao, 
          'preco': preco, 
          'estoque': estoque,
          'foto': foto,
        }),
      );
      final resData = jsonDecode(response.body);
      if (!mounted) return;
      if (response.statusCode == 201 && resData['sucesso'] == true) {
        _mostrarSnack('✅ Produto cadastrado com sucesso!');
        _carregarProdutos();
      } else {
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Falha ao cadastrar.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _removerProdutoAPI(int produtoId) async {
    try {
      final response = await http.delete(
        Uri.parse('$_apiUrl/$produtoId'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('🗑️ Produto removido!');
        _carregarProdutos();
      } else {
        _mostrarSnack('Erro ao remover produto.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _abrirDialogoNovoProduto() {
    final nomeCtrl = TextEditingController();
    final descricaoCtrl = TextEditingController();
    final precoCtrl = TextEditingController();
    final estoqueCtrl = TextEditingController();
    String fotoBase64 = '';
    Uint8List? imagemBytesWeb;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) {
          Future<void> selecionarImagem(ImageSource source) async {
            final picker = ImagePicker();
            final pickedFile = await picker.pickImage(source: source, imageQuality: 70);
            if (pickedFile != null) {
              final bytes = await pickedFile.readAsBytes();
              setDialogState(() {
                imagemBytesWeb = bytes;
                fotoBase64 = 'data:image/jpeg;base64,${base64Encode(bytes)}';
              });
            }
          }

          return AlertDialog(
            backgroundColor: _cardDark,
            title: const Text('CADASTRAR NOVO PRODUTO', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  GestureDetector(
                    onTap: () {
                      showModalBottomSheet(
                        context: context,
                        backgroundColor: _cardDark,
                        builder: (_) => SafeArea(
                          child: Wrap(
                            children: [
                              ListTile(
                                leading: const Icon(Icons.camera_alt, color: Colors.white),
                                title: const Text('Tirar Foto com a Câmera', style: TextStyle(color: Colors.white)),
                                onTap: () {
                                  Navigator.pop(context);
                                  selecionarImagem(ImageSource.camera);
                                },
                              ),
                              ListTile(
                                leading: const Icon(Icons.photo_library, color: Colors.white),
                                title: const Text('Escolher da Galeria', style: TextStyle(color: Colors.white)),
                                onTap: () {
                                  Navigator.pop(context);
                                  selecionarImagem(ImageSource.gallery);
                                },
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                    child: Container(
                      width: 80,
                      height: 80,
                      decoration: BoxDecoration(
                        color: const Color(0xFF1C1C1C),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.white24),
                      ),
                      child: imagemBytesWeb != null
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(12),
                              child: Image.memory(imagemBytesWeb!, fit: BoxFit.cover),
                            )
                          : Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.add_a_photo, color: _brandRed, size: 28),
                                const SizedBox(height: 4),
                                const Text('Foto', style: TextStyle(color: Colors.white54, fontSize: 10)),
                              ],
                            ),
                    ),
                  ),
                  const SizedBox(height: 16),

                  TextField(
                    controller: nomeCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Nome do Produto', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: descricaoCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Descrição do Produto', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: precoCtrl,
                    keyboardType: TextInputType.number,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Preço (Ex: 45.00)', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: estoqueCtrl,
                    keyboardType: TextInputType.number,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Estoque Inicial', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
                onPressed: () {
                  final preco = double.tryParse(precoCtrl.text.trim().replaceAll(',', '.'));
                  if (nomeCtrl.text.isNotEmpty && preco != null) {
                    Navigator.pop(ctx);
                    _cadastrarProdutoAPI(
                      nomeCtrl.text.trim(), 
                      descricaoCtrl.text.trim(), 
                      preco, 
                      int.tryParse(estoqueCtrl.text) ?? 0,
                      fotoBase64,
                    );
                  } else {
                    _mostrarSnack('Preencha nome e um preço válido.');
                  }
                },
                child: const Text('Salvar', style: TextStyle(color: Colors.white)),
              ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('GERENCIAR PRODUTOS', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: Colors.white), onPressed: _carregarProdutos),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Novo Produto', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        onPressed: _abrirDialogoNovoProduto,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _produtos.isEmpty
              ? Center(child: Text('Nenhum produto cadastrado.', style: TextStyle(color: _textSecondary)))
              : RefreshIndicator(
                  onRefresh: _carregarProdutos,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _produtos.length,
                    itemBuilder: (context, index) {
                      final prod = _produtos[index];
                      final double preco = double.tryParse(prod['preco'].toString()) ?? 0;
                      final String nome = prod['nome'] ?? '';
                      final String foto = prod['foto'] ?? '';
                      final String primeiraLetra = nome.isNotEmpty ? nome.substring(0, 1).toUpperCase() : 'P';

                      return Container(
                        margin: const EdgeInsets.only(bottom: 12),
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: _cardDark,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: Colors.white10),
                        ),
                        child: Row(
                          children: [
                            Container(
                              width: 45,
                              height: 45,
                              decoration: BoxDecoration(
                                color: const Color(0xFF1C1C1C),
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: Colors.white10),
                              ),
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: foto.trim().isNotEmpty
                                    ? (foto.startsWith('data:image')
                                        ? Image.memory(base64Decode(foto.split(',')[1]), fit: BoxFit.cover)
                                        : Image.network(foto, fit: BoxFit.cover, errorBuilder: (_,__,___) => Center(child: Text(primeiraLetra, style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 18)))))
                                    : Center(
                                        child: Text(
                                          primeiraLetra,
                                          style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 18),
                                        ),
                                      ),
                              ),
                            ),
                            const SizedBox(width: 14),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    nome,
                                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                                  ),
                                  const SizedBox(height: 4),
                                  Text(
                                    'Estoque: ${prod['estoque']} un • ${prod['descricao'] ?? ''}',
                                    style: TextStyle(color: _textSecondary, fontSize: 12),
                                  ),
                                ],
                              ),
                            ),
                            Text(
                              'R\$ ${preco.toStringAsFixed(2).replaceAll('.', ',')}',
                              style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 15),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, color: Colors.white38, size: 20),
                              onPressed: () => _removerProdutoAPI(prod['id']),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

class GerenciarPacotesScreen extends StatefulWidget {
  const GerenciarPacotesScreen({super.key});

  @override
  State<GerenciarPacotesScreen> createState() => _GerenciarPacotesScreenState();
}

class _GerenciarPacotesScreenState extends State<GerenciarPacotesScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _apiUrl = '${AppConfig.apiUrl}/admin/combos';

  List<dynamic> _pacotes = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _carregarPacotes();
  }

  Future<void> _carregarPacotes() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _pacotes = data['combos'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar pacotes.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _cadastrarComboAPI(String nome, String tipo, int sessoes, double preco, double desconto) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome,
          'tipo': tipo,
          'sessoes': sessoes,
          'preco': preco,
          'desconto_percentual': desconto,
        }),
      );
      final resData = jsonDecode(response.body);
      if (!mounted) return;
      if (response.statusCode == 201 && resData['sucesso'] == true) {
        _mostrarSnack('✅ Pacote cadastrado com sucesso!');
        _carregarPacotes();
      } else {
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Falha ao cadastrar.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _removerComboAPI(int comboId) async {
    try {
      final response = await http.delete(
        Uri.parse('$_apiUrl/$comboId'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('🗑️ Pacote removido!');
        _carregarPacotes();
      } else {
        _mostrarSnack('Erro ao remover pacote.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _abrirDialogoNovoPacote() {
    final nomeCtrl = TextEditingController();
    final sessoesCtrl = TextEditingController(text: '1');
    final precoCtrl = TextEditingController();
    final descontoCtrl = TextEditingController(text: '0');
    String tipoSelecionado = 'servico';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: _cardDark,
          title: const Text('CADASTRAR NOVO PACOTE', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: nomeCtrl,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(labelText: 'Nome do Pacote', labelStyle: TextStyle(color: Colors.grey)),
                ),
                const SizedBox(height: 10),
                DropdownButtonFormField<String>(
                  value: tipoSelecionado,
                  dropdownColor: _cardDark,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(labelText: 'Tipo', labelStyle: TextStyle(color: Colors.grey)),
                  items: const [
                    DropdownMenuItem(value: 'servico', child: Text('Combo de Serviços')),
                    DropdownMenuItem(value: 'produto', child: Text('Combo de Produtos')),
                  ],
                  onChanged: (v) => setDialogState(() => tipoSelecionado = v ?? 'servico'),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: sessoesCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(labelText: 'Sessões/Quantidade', labelStyle: TextStyle(color: Colors.grey)),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: precoCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(labelText: 'Preço do Pacote (Ex: 130.00)', labelStyle: TextStyle(color: Colors.grey)),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: descontoCtrl,
                  keyboardType: TextInputType.number,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(labelText: '% de Desconto (Ex: 15)', labelStyle: TextStyle(color: Colors.grey)),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
            ),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
              onPressed: () {
                final preco = double.tryParse(precoCtrl.text.trim().replaceAll(',', '.'));
                if (nomeCtrl.text.isNotEmpty && preco != null) {
                  Navigator.pop(ctx);
                  _cadastrarComboAPI(
                    nomeCtrl.text.trim(),
                    tipoSelecionado,
                    int.tryParse(sessoesCtrl.text) ?? 1,
                    preco,
                    double.tryParse(descontoCtrl.text.replaceAll(',', '.')) ?? 0,
                  );
                } else {
                  _mostrarSnack('Preencha nome e um preço válido.');
                }
              },
              child: const Text('Salvar', style: TextStyle(color: Colors.white)),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('GERENCIAR PACOTES', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: Colors.white), onPressed: _carregarPacotes),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Novo Pacote', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        onPressed: _abrirDialogoNovoPacote,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _pacotes.isEmpty
              ? Center(child: Text('Nenhum pacote cadastrado.', style: TextStyle(color: _textSecondary)))
              : RefreshIndicator(
                  onRefresh: _carregarPacotes,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _pacotes.length,
                    itemBuilder: (context, index) {
                      final pacote = _pacotes[index];
                      final double preco = double.tryParse(pacote['preco'].toString()) ?? 0;
                      final double desconto = double.tryParse(pacote['desconto_percentual'].toString()) ?? 0;
                      final bool ehServico = (pacote['tipo'] ?? 'servico') == 'servico';

                      return Container(
                        margin: const EdgeInsets.only(bottom: 12),
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: _cardDark,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: Colors.white10),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Expanded(
                                  child: Row(
                                    children: [
                                      Icon(ehServico ? Icons.content_cut : Icons.shopping_bag_outlined, color: _brandRed, size: 18),
                                      const SizedBox(width: 8),
                                      Expanded(
                                        child: Text(
                                          pacote['nome'] ?? '',
                                          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                if (desconto > 0)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: Colors.green.withOpacity(0.2),
                                      borderRadius: BorderRadius.circular(6),
                                      border: Border.all(color: Colors.green),
                                    ),
                                    child: Text(
                                      '${desconto.toStringAsFixed(0)}% de Economia',
                                      style: const TextStyle(color: Colors.greenAccent, fontSize: 10, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                              ],
                            ),
                            const SizedBox(height: 8),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                Text('Sessões: ${pacote['sessoes']}', style: TextStyle(color: _textSecondary, fontSize: 13)),
                                Row(
                                  children: [
                                    Text(
                                      'R\$ ${preco.toStringAsFixed(2).replaceAll('.', ',')}',
                                      style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 16),
                                    ),
                                    IconButton(
                                      icon: const Icon(Icons.delete_outline, color: Colors.white38, size: 20),
                                      onPressed: () => _removerComboAPI(pacote['id']),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

// ==============================================================================
// GERENCIAR ASSINATURAS (COM FILTRO DE DATA E BOTÃO X)
// ==============================================================================

class GerenciarAssinaturasScreen extends StatefulWidget {
  const GerenciarAssinaturasScreen({super.key});

  @override
  State<GerenciarAssinaturasScreen> createState() => _GerenciarAssinaturasScreenState();
}

class _GerenciarAssinaturasScreenState extends State<GerenciarAssinaturasScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _apiUrl = '${AppConfig.apiUrl}/admin/planos-ativos';

  List<dynamic> _planos = [];
  bool _isLoading = true;
  String? _dataFiltro; // Formato YYYY-MM-DD

  @override
  void initState() {
    super.initState();
    _carregarPlanos();
  }

  Future<void> _carregarPlanos() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(Uri.parse(_apiUrl), headers: AppConfig.adminHeaders);
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _planos = data['planos'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
    }
  }

  Future<void> selecionarDataFiltro() async {
    DateTime? picked = await showDatePicker(
      context: context,
      initialDate: DateTime.now(),
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(
              primary: _brandRed,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );

    if (picked != null) {
      setState(() {
        _dataFiltro = "${picked.year}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}";
      });
    }
  }

  void _limparFiltroData() {
    setState(() {
      _dataFiltro = null;
    });
  }

  Future<void> _solicitarCobrancaAPI(int assinaturaId, String nomeCliente) async {
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiUrl}/admin/cobrar-assinatura'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({'assinatura_id': assinaturaId}),
      );
      final resData = jsonDecode(response.body);
      if (!mounted) return;

      if (response.statusCode == 200 && resData['sucesso'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('💳 Cobrança solicitada para $nomeCliente com sucesso!'), backgroundColor: Colors.teal),
        );
        _carregarPlanos();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ ${resData['mensagem'] ?? 'Falha ao solicitar cobrança.'}'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Erro de conexão com o servidor.'), backgroundColor: Colors.red),
      );
    }
  }

  Future<void> _cancelarAssinaturaAPI(int assinaturaId, String nomeCliente) async {
    try {
      final response = await http.post(
        Uri.parse('${AppConfig.apiUrl}/admin/cancelar-assinatura'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({'assinatura_id': assinaturaId}),
      );
      final resData = jsonDecode(response.body);
      if (!mounted) return;

      if (response.statusCode == 200 && resData['sucesso'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('🚫 Assinatura de $nomeCliente cancelada com sucesso!'), backgroundColor: Colors.orange),
        );
        _carregarPlanos();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ ${resData['mensagem'] ?? 'Erro ao cancelar.'}'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Erro de conexão com o servidor.'), backgroundColor: Colors.red),
      );
    }
  }

  void _abrirListaFiltrada(String titulo, List<dynamic> listaFiltro) {
    showModalBottomSheet(
      context: context,
      backgroundColor: _cardDark,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) {
        return DraggableScrollableSheet(
          initialChildSize: 0.85,
          minChildSize: 0.5,
          maxChildSize: 0.95,
          expand: false,
          builder: (_, controller) {
            return Padding(
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Center(
                    child: Container(
                      width: 40,
                      height: 4,
                      decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(2)),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    titulo,
                    style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                  ),
                  const Divider(color: Colors.white10, height: 20),
                  Expanded(
                    child: listaFiltro.isEmpty
                        ? Center(
                            child: Text('Nenhum registro encontrado.', style: TextStyle(color: _textSecondary, fontSize: 13)),
                          )
                        : ListView.builder(
                            controller: controller,
                            itemCount: listaFiltro.length,
                            itemBuilder: (context, index) {
                              final p = listaFiltro[index];
                              
                              String statusBanco = (p['status'] ?? 'ativo').toString().toLowerCase();
                              bool isAtivo = statusBanco == 'ativo' || statusBanco == 'active';
                              Color corStatus = isAtivo ? Colors.greenAccent : _brandRed;
                              String textoStatus = isAtivo ? 'ATIVO' : 'CANCELADO';

                              return InkWell(
                                onTap: () => _abrirDetalhesAssinatura(p),
                                borderRadius: BorderRadius.circular(12),
                                child: Container(
                                margin: const EdgeInsets.only(bottom: 12),
                                padding: const EdgeInsets.all(16),
                                decoration: BoxDecoration(
                                  color: _cardDark,
                                  borderRadius: BorderRadius.circular(12),
                                  border: Border.all(color: corStatus.withOpacity(0.3)),
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Expanded(
                                          child: Column(
                                            crossAxisAlignment: CrossAxisAlignment.start,
                                            children: [
                                              Text(p['cliente_nome'] ?? 'Cliente', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
                                              const SizedBox(height: 2),
                                              Text(p['cliente_email'] ?? '', style: TextStyle(color: _textSecondary, fontSize: 12)),
                                            ],
                                          ),
                                        ),
                                        Container(
                                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                          decoration: BoxDecoration(color: corStatus.withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
                                          child: Text(textoStatus, style: TextStyle(color: corStatus, fontSize: 9, fontWeight: FontWeight.bold)),
                                        ),
                                      ],
                                    ),
                                    const Divider(color: Colors.white10, height: 20),
                                    Row(
                                      children: [
                                        Icon(Icons.card_membership, color: _brandRed, size: 18),
                                        const SizedBox(width: 8),
                                        Expanded(child: Text(p['nome'] ?? 'Plano', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13))),
                                        const SizedBox(width: 8),
                                        Text('R\$ ${(double.tryParse('${p['preco']}') ?? 0).toStringAsFixed(2).replaceAll('.', ',')}', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14)),
                                      ],
                                    ),
                                    const SizedBox(height: 12),
                                    Row(
                                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                      children: [
                                        Text('Validade: ${p['validade'] ?? '--/--/----'}', style: TextStyle(color: _textSecondary, fontSize: 12)),
                                        if (isAtivo)
                                          Row(
                                            children: [
                                              ElevatedButton.icon(
                                                style: ElevatedButton.styleFrom(
                                                  backgroundColor: _brandRed,
                                                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                                                  minimumSize: const Size(0, 28),
                                                ),
                                                onPressed: () => _cancelarAssinaturaAPI(p['id'], p['cliente_nome'] ?? 'Cliente'),
                                                icon: const Icon(Icons.block, size: 12, color: Colors.white),
                                                label: const Text('Cancelar', style: TextStyle(color: Colors.white, fontSize: 10)),
                                              ),
                                              const SizedBox(width: 6),
                                              ElevatedButton.icon(
                                                style: ElevatedButton.styleFrom(
                                                  backgroundColor: Colors.teal,
                                                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                                                  minimumSize: const Size(0, 28),
                                                ),
                                                onPressed: () => _solicitarCobrancaAPI(p['id'], p['cliente_nome'] ?? 'Cliente'),
                                                icon: const Icon(Icons.payment, size: 12, color: Colors.white),
                                                label: const Text('Cobrar', style: TextStyle(color: Colors.white, fontSize: 10)),
                                              ),
                                            ],
                                          ),
                                      ],
                                    ),
                                  ],
                                ),
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    // Aplica o filtro de data caso esteja selecionada
    List<dynamic> planosFiltrados = _planos;
    if (_dataFiltro != null) {
      planosFiltrados = _planos.where((p) {
        String validade = (p['validade'] ?? '').toString();
        // Converte DD/MM/YYYY para YYYY-MM-DD se necessário para bater com o filtro
        return validade.contains(_dataFiltro!) || (p['inicio'] ?? '').toString().contains(_dataFiltro!);
      }).toList();
    }

    List<dynamic> ativosList = planosFiltrados.where((p) => (p['status'] ?? '').toString().toLowerCase() == 'ativo').toList();
    List<dynamic> vencidosList = planosFiltrados.where((p) => (p['status'] ?? '').toString().toLowerCase() == 'vencido').toList();
    List<dynamic> canceladosList = planosFiltrados.where((p) {
      String st = (p['status'] ?? '').toString().toLowerCase();
      return st == 'inativo' || st == 'cancelado';
    }).toList();

    double totalValor = ativosList.fold(0.0, (sum, p) => sum + (double.tryParse('${p['preco']}') ?? 0.0));

    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('STATUS DE ASSINATURAS', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(
            icon: Icon(Icons.calendar_month, color: _brandRed),
            tooltip: 'Filtrar por Data',
            onPressed: selecionarDataFiltro,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white),
            onPressed: _carregarPlanos,
          ),
        ],
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : RefreshIndicator(
              onRefresh: _carregarPlanos,
              color: _brandRed,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  // Card indicador de Data Fixada com botão X para limpar (igual ao Financeiro)
                  if (_dataFiltro != null) ...[
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                      decoration: BoxDecoration(
                        color: _brandRed.withOpacity(0.12),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: _brandRed.withOpacity(0.4)),
                      ),
                      child: Row(
                        children: [
                          Icon(Icons.push_pin, color: _brandRed, size: 16),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              'Data filtrada: $_dataFiltro',
                              style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
                            ),
                          ),
                          InkWell(
                            onTap: _limparFiltroData,
                            borderRadius: BorderRadius.circular(20),
                            child: Container(
                              padding: const EdgeInsets.all(4),
                              decoration: BoxDecoration(
                                color: Colors.white.withOpacity(0.08),
                                shape: BoxShape.circle,
                              ),
                              child: const Icon(Icons.close, color: Colors.white70, size: 16),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: _cardDark,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      children: [
                        const Text('Resumo Geral', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13)),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _buildDashCard('Ativos', '${ativosList.length}', Colors.greenAccent, () {
                              _abrirListaFiltrada('Assinaturas Ativas', ativosList);
                            }),
                            const SizedBox(width: 8),
                            _buildDashCard('Vencidos', '${vencidosList.length}', Colors.orangeAccent, () {
                              _abrirListaFiltrada('Assinaturas Vencidas', vencidosList);
                            }),
                            const SizedBox(width: 8),
                            _buildDashCard('Cancelados', '${canceladosList.length}', _brandRed, () {
                              _abrirListaFiltrada('Assinaturas Canceladas', canceladosList);
                            }),
                          ],
                        ),
                        const SizedBox(height: 10),
                        Container(
                          width: double.infinity,
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: Colors.black,
                            borderRadius: BorderRadius.circular(8),
                            border: Border.all(color: Colors.white12),
                          ),
                          child: Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              const Text('Receita Recorrente Ativa:', style: TextStyle(color: Colors.grey, fontSize: 12)),
                              Text('R\$ ${totalValor.toStringAsFixed(2).replaceAll('.', ',')}', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  const Text('Lista de Assinaturas Ativas e Vencidas', style: TextStyle(color: Colors.white70, fontSize: 13, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 10),

                  ...ativosList.map((p) => _buildAssinaturaCard(p, true)),
                  ...vencidosList.map((p) => _buildAssinaturaCard(p, false)),

                  if (ativosList.isEmpty && vencidosList.isEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 40),
                      child: Center(
                        child: Text('Nenhuma assinatura ativa ou vencida encontrada.', style: TextStyle(color: _textSecondary)),
                      ),
                    ),
                ],
              ),
            ),
    );
  }

  Widget _buildDashCard(String titulo, String valor, Color cor, VoidCallback onTap) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
          decoration: BoxDecoration(
            color: Colors.black,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: cor.withOpacity(0.4)),
          ),
          child: Column(
            children: [
              Text(titulo, style: const TextStyle(color: Colors.grey, fontSize: 12, fontWeight: FontWeight.w500)),
              const SizedBox(height: 6),
              Text(valor, style: TextStyle(color: cor, fontWeight: FontWeight.bold, fontSize: 18)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildAssinaturaCard(Map<String, dynamic> p, bool isAtivo) {
    Color corStatus = isAtivo ? Colors.greenAccent : Colors.orangeAccent;
    String textoStatus = isAtivo ? 'ATIVO' : 'VENCIDO / SALDO INSUFICIENTE';

    return InkWell(
      onTap: () => _abrirDetalhesAssinatura(p),
      borderRadius: BorderRadius.circular(12),
      child: Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _cardDark,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: corStatus.withOpacity(0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(p['cliente_nome'] ?? 'Cliente', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
                    const SizedBox(height: 2),
                    Text(p['cliente_email'] ?? '', style: TextStyle(color: _textSecondary, fontSize: 12)),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(color: corStatus.withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
                child: Text(textoStatus, style: TextStyle(color: corStatus, fontSize: 9, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
          const Divider(color: Colors.white10, height: 20),
          Row(
            children: [
              Icon(Icons.card_membership, color: _brandRed, size: 18),
              const SizedBox(width: 8),
              Expanded(child: Text(p['nome'] ?? 'Plano', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13))),
              const SizedBox(width: 8),
              Text('R\$ ${(double.tryParse('${p['preco']}') ?? 0).toStringAsFixed(2).replaceAll('.', ',')}', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14)),
            ],
          ),
          const SizedBox(height: 12),
          LayoutBuilder(
            builder: (context, constraints) {
              return Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Text('Validade: ${p['validade'] ?? '--/--/----'}', style: TextStyle(color: _textSecondary, fontSize: 12)),
                  ),
                  Wrap(
                    spacing: 4,
                    runSpacing: 4,
                    alignment: WrapAlignment.end,
                    children: [
                      if (isAtivo)
                        ElevatedButton.icon(
                          style: ElevatedButton.styleFrom(
                            backgroundColor: _brandRed,
                            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                            minimumSize: const Size(0, 28),
                          ),
                          onPressed: () => _cancelarAssinaturaAPI(p['id'], p['cliente_nome'] ?? 'Cliente'),
                          icon: const Icon(Icons.block, size: 12, color: Colors.white),
                          label: const Text('Cancelar', style: TextStyle(color: Colors.white, fontSize: 10)),
                        ),
                      ElevatedButton.icon(
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.teal,
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 4),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(6)),
                          minimumSize: const Size(0, 28),
                        ),
                        onPressed: () => _solicitarCobrancaAPI(p['id'], p['cliente_nome'] ?? 'Cliente'),
                        icon: const Icon(Icons.payment, size: 12, color: Colors.white),
                        label: const Text('Cobrar', style: TextStyle(color: Colors.white, fontSize: 10)),
                      ),
                    ],
                  ),
                ],
              );
            },
          ),
        ],
      ),
      ),
    );
  }

  String _txtOuTraco(dynamic v) {
    final s = (v ?? '').toString().trim();
    return (s.isEmpty || s == 'null') ? '—' : s;
  }

  String _situacaoValidade(String validade) {
    final p = validade.split('/');
    if (p.length != 3) return '—';
    final d = int.tryParse(p[0]);
    final m = int.tryParse(p[1]);
    final a = int.tryParse(p[2]);
    if (d == null || m == null || a == null) return '—';
    final hoje = DateTime.now();
    final dias = DateTime(a, m, d).difference(DateTime(hoje.year, hoje.month, hoje.day)).inDays;
    if (dias > 0) return 'Vence em $dias dia(s)';
    if (dias == 0) return 'Vence hoje';
    return 'Venceu há ${-dias} dia(s)';
  }

  Widget _linhaDetalhe(IconData icone, String rotulo, String valor, {Color? corValor}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icone, color: _brandRed, size: 18),
          const SizedBox(width: 10),
          Expanded(flex: 4, child: Text(rotulo, style: TextStyle(color: _textSecondary, fontSize: 12))),
          Expanded(
            flex: 6,
            child: SelectableText(
              valor,
              textAlign: TextAlign.right,
              style: TextStyle(color: corValor ?? Colors.white, fontSize: 13, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }

  Widget _tituloSecaoDetalhe(String texto) {
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 2),
      child: Text(texto, style: TextStyle(color: _textSecondary, fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 1)),
    );
  }

  void _abrirDetalhesAssinatura(dynamic p) {
    final st = (p['status'] ?? '').toString().toLowerCase();
    final Color cor = st == 'ativo' ? Colors.greenAccent : (st == 'vencido' ? Colors.orangeAccent : _brandRed);
    final String textoStatus = st == 'ativo' ? 'ATIVA' : (st == 'vencido' ? 'VENCIDA' : 'CANCELADA');
    final preco = double.tryParse('${p['preco']}') ?? 0;
    final validade = (p['validade'] ?? '').toString();

    showModalBottomSheet(
      context: context,
      backgroundColor: _cardDark,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) {
        return SafeArea(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(color: Colors.white24, borderRadius: BorderRadius.circular(2)),
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        _txtOuTraco(p['nome_plano'] ?? p['nome']),
                        style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.bold),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(color: cor.withOpacity(0.15), borderRadius: BorderRadius.circular(6)),
                      child: Text(textoStatus, style: TextStyle(color: cor, fontSize: 11, fontWeight: FontWeight.bold)),
                    ),
                  ],
                ),
                _tituloSecaoDetalhe('CLIENTE'),
                _linhaDetalhe(Icons.person_outline, 'Nome', _txtOuTraco(p['cliente_nome'])),
                _linhaDetalhe(Icons.email_outlined, 'E-mail', _txtOuTraco(p['cliente_email'])),
                _linhaDetalhe(Icons.phone_outlined, 'Telefone', _txtOuTraco(p['cliente_telefone'])),
                _linhaDetalhe(Icons.event_available_outlined, 'Cliente desde', _txtOuTraco(p['cliente_desde'])),
                _tituloSecaoDetalhe('PLANO'),
                _linhaDetalhe(Icons.card_membership, 'Plano', _txtOuTraco(p['nome_plano'] ?? p['nome'])),
                _linhaDetalhe(Icons.attach_money, 'Valor mensal',
                    'R\$ ${preco.toStringAsFixed(2).replaceAll('.', ',')}', corValor: _brandRed),
                _linhaDetalhe(Icons.flag_outlined, 'Situação', textoStatus, corValor: cor),
                _linhaDetalhe(Icons.edit_calendar_outlined, 'Assinada em', _txtOuTraco(p['assinada_em'])),
                _linhaDetalhe(Icons.play_circle_outline, 'Início do período', _txtOuTraco(p['inicio'])),
                _linhaDetalhe(Icons.event_repeat, 'Validade / renovação', _txtOuTraco(p['validade'])),
                _linhaDetalhe(Icons.hourglass_bottom, 'Prazo', _situacaoValidade(validade)),
                _tituloSecaoDetalhe('USO E PAGAMENTO'),
                _linhaDetalhe(Icons.content_cut, 'Cortes usando o plano (no período)', _txtOuTraco(p['usos_plano'] ?? 0)),
                _linhaDetalhe(Icons.tag, 'Nº da assinatura', '#${_txtOuTraco(p['id'])}'),
                _linhaDetalhe(Icons.receipt_long_outlined, 'ID no Mercado Pago', _txtOuTraco(p['gateway_subscription_id'])),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  height: 44,
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.white24),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                    onPressed: () => Navigator.pop(ctx),
                    child: const Text('Fechar', style: TextStyle(color: Colors.white)),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ==============================================================================
// GERENCIAR SERVIÇOS
// ==============================================================================

class GerenciarServicosScreen extends StatefulWidget {
  const GerenciarServicosScreen({super.key});

  @override
  State<GerenciarServicosScreen> createState() => _GerenciarServicosScreenState();
}

class _GerenciarServicosScreenState extends State<GerenciarServicosScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _apiUrl = '${AppConfig.apiUrl}/admin/servicos';

  List<dynamic> _servicos = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _carregarServicos();
  }

  Future<void> _carregarServicos() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _servicos = data['servicos'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar serviços.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _salvarPrecoAPI(String nome, double preco, String categoria, String foto) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome, 
          'preco': preco,
          'categoria': categoria,
          'foto': foto,
        }),
      );
      if (!mounted) return;
      if (response.statusCode == 201) {
        _mostrarSnack('✅ Serviço salvo com sucesso!');
        _carregarServicos();
      } else {
        _mostrarSnack('Erro ao salvar serviço.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _removerServicoAPI(int id) async {
    try {
      final response = await http.delete(
        Uri.parse('$_apiUrl/$id'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('🗑️ Removido!');
        _carregarServicos();
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _atualizarServicoAPI(int id, String nome, double preco, String categoria, String foto) async {
    try {
      final response = await http.put(
        Uri.parse('$_apiUrl/$id'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome,
          'preco': preco,
          'categoria': categoria,
          'foto': foto,
        }),
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('✅ Serviço atualizado com sucesso!');
        _carregarServicos();
      } else {
        _mostrarSnack('Erro ao atualizar serviço.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _abrirDialogoNovoServico({Map<String, dynamic>? servicoExistente}) {
    final bool editando = servicoExistente != null;
    final nomeCtrl = TextEditingController(text: servicoExistente?['nome'] ?? '');
    final precoCtrl = TextEditingController(
      text: servicoExistente != null ? (double.tryParse('${servicoExistente['preco']}') ?? 0).toStringAsFixed(2) : '',
    );
    String categoriaSelecionada = servicoExistente?['categoria'] ?? 'Cabelo';
    String fotoBase64 = servicoExistente?['foto'] ?? '';
    Uint8List? imagemBytesWeb = fotoBase64.startsWith('data:image')
        ? base64Decode(fotoBase64.split(',')[1])
        : null;

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (context, setDialogState) {
          Future<void> selecionarImagem(ImageSource source) async {
            final picker = ImagePicker();
            final pickedFile = await picker.pickImage(source: source, imageQuality: 70);
            if (pickedFile != null) {
              final bytes = await pickedFile.readAsBytes();
              setDialogState(() {
                imagemBytesWeb = bytes;
                fotoBase64 = 'data:image/jpeg;base64,${base64Encode(bytes)}';
              });
            }
          }

          return AlertDialog(
            backgroundColor: _cardDark,
            title: Text(
              editando ? 'EDITAR SERVIÇO' : 'CADASTRAR / DEFINIR SERVIÇO',
              style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Text(
                    'Digite o nome exatamente como aparece no agendamento.',
                    style: TextStyle(color: _textSecondary, fontSize: 12),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 16),
                  
                  GestureDetector(
                    onTap: () {
                      showModalBottomSheet(
                        context: context,
                        backgroundColor: _cardDark,
                        builder: (_) => SafeArea(
                          child: Wrap(
                            children: [
                              ListTile(
                                leading: const Icon(Icons.camera_alt, color: Colors.white),
                                title: const Text('Tirar Foto com a Câmera', style: TextStyle(color: Colors.white)),
                                onTap: () {
                                  Navigator.pop(context);
                                  selecionarImagem(ImageSource.camera);
                                },
                              ),
                              ListTile(
                                leading: const Icon(Icons.photo_library, color: Colors.white),
                                title: const Text('Escolher da Galeria', style: TextStyle(color: Colors.white)),
                                onTap: () {
                                  Navigator.pop(context);
                                  selecionarImagem(ImageSource.gallery);
                                },
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                    child: Container(
                      width: 80,
                      height: 80,
                      decoration: BoxDecoration(
                        color: const Color(0xFF1C1C1C),
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.white24),
                      ),
                      child: imagemBytesWeb != null
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(12),
                              child: Image.memory(imagemBytesWeb!, fit: BoxFit.cover),
                            )
                          : Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.add_a_photo, color: _brandRed, size: 28),
                                const SizedBox(height: 4),
                                const Text('Foto', style: TextStyle(color: Colors.white54, fontSize: 10)),
                              ],
                            ),
                    ),
                  ),
                  const SizedBox(height: 16),

                  TextField(
                    controller: nomeCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Nome do Serviço', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    value: categoriaSelecionada,
                    dropdownColor: _cardDark,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Categoria',
                      labelStyle: TextStyle(color: Colors.grey),
                    ),
                    items: const [
                      DropdownMenuItem(value: 'Cabelo', child: Text('Cabelo')),
                      DropdownMenuItem(value: 'Barba', child: Text('Barba')),
                      DropdownMenuItem(value: 'Tratamentos', child: Text('Tratamentos')),
                      DropdownMenuItem(value: 'Química', child: Text('Química')),
                    ],
                    onChanged: (v) {
                      setDialogState(() {
                        categoriaSelecionada = v ?? 'Cabelo';
                      });
                    },
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: precoCtrl,
                    keyboardType: TextInputType.number,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(labelText: 'Preço (Ex: 35.00)', labelStyle: TextStyle(color: Colors.grey)),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
                onPressed: () {
                  final preco = double.tryParse(precoCtrl.text.trim().replaceAll(',', '.'));
                  if (nomeCtrl.text.trim().isNotEmpty && preco != null) {
                    Navigator.pop(ctx);
                    if (editando) {
                      _atualizarServicoAPI(
                        servicoExistente!['id'] as int,
                        nomeCtrl.text.trim(),
                        preco,
                        categoriaSelecionada,
                        fotoBase64,
                      );
                    } else {
                      _salvarPrecoAPI(
                        nomeCtrl.text.trim(), 
                        preco, 
                        categoriaSelecionada, 
                        fotoBase64
                      );
                    }
                  } else {
                    _mostrarSnack('Preencha nome e um preço válido.');
                  }
                },
                child: Text(editando ? 'Salvar Alterações' : 'Salvar', style: const TextStyle(color: Colors.white)),
              ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('PREÇO DOS SERVIÇOS', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: Colors.white), onPressed: _carregarServicos),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Novo Serviço', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        onPressed: _abrirDialogoNovoServico,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _servicos.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      'Nenhum preço cadastrado ainda. Sem isso, o Financeiro mostra R\$ 0,00 nos cortes finalizados.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: _textSecondary),
                    ),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _carregarServicos,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: _servicos.length,
                    itemBuilder: (context, index) {
                      final s = _servicos[index];
                      final double preco = double.tryParse(s['preco'].toString()) ?? 0;
                      final String categoria = s['categoria'] ?? 'Geral';
                      final String nome = s['nome'] ?? '';
                      final String foto = s['foto'] ?? '';
                      final String primeiraLetra = nome.isNotEmpty ? nome.substring(0, 1).toUpperCase() : 'S';

                      return Container(
                        margin: const EdgeInsets.only(bottom: 10),
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                        decoration: BoxDecoration(
                          color: _cardDark,
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(color: Colors.white10),
                        ),
                        child: Row(
                          children: [
                            Container(
                              width: 45,
                              height: 45,
                              decoration: BoxDecoration(
                                color: const Color(0xFF1C1C1C),
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: Colors.white10),
                              ),
                              child: ClipRRect(
                                borderRadius: BorderRadius.circular(8),
                                child: foto.trim().isNotEmpty
                                    ? (foto.startsWith('data:image')
                                        ? Image.memory(base64Decode(foto.split(',')[1]), fit: BoxFit.cover)
                                        : Image.network(foto, fit: BoxFit.cover, errorBuilder: (_,__,___) => Center(child: Text(primeiraLetra, style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 18)))))
                                    : Center(
                                        child: Text(
                                          primeiraLetra,
                                          style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 18),
                                        ),
                                      ),
                              ),
                            ),
                            const SizedBox(width: 14),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    nome,
                                    style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 14),
                                  ),
                                  const SizedBox(height: 4),
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                                    decoration: BoxDecoration(
                                      color: _brandRed.withOpacity(0.15),
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: Text(
                                      categoria.toUpperCase(),
                                      style: TextStyle(color: _brandRed, fontSize: 10, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Text(
                              'R\$ ${preco.toStringAsFixed(2).replaceAll('.', ',')}',
                              style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14),
                            ),
                            IconButton(
                              icon: const Icon(Icons.edit_outlined, color: Colors.orangeAccent, size: 20),
                              tooltip: 'Editar Serviço',
                              onPressed: () => _abrirDialogoNovoServico(servicoExistente: s),
                            ),
                            IconButton(
                              icon: const Icon(Icons.delete_outline, color: Colors.white38, size: 20),
                              onPressed: () => _removerServicoAPI(s['id']),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

// ==============================================================================
// GERENCIAR PLANOS DE ASSINATURA (ORGANIZADO E AJUSTADO)
// ==============================================================================

class GerenciarPlanosScreen extends StatefulWidget {
  const GerenciarPlanosScreen({super.key});

  @override
  State<GerenciarPlanosScreen> createState() => _GerenciarPlanosScreenState();
}

class _GerenciarPlanosScreenState extends State<GerenciarPlanosScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _apiUrl = '${AppConfig.apiUrl}/admin/planos';

  List<dynamic> _planos = [];
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();
    _carregarPlanos();
  }

  Future<void> _carregarPlanos() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(Uri.parse(_apiUrl), headers: AppConfig.adminHeaders);
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _planos = data['planos'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar planos.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _cadastrarPlanoAPI(String nome, String descricao, double preco, int ordem) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({'nome': nome, 'descricao': descricao, 'preco': preco, 'ordem': ordem}),
      );
      final resData = jsonDecode(response.body);
      if (!mounted) return;
      if (response.statusCode == 201 && resData['sucesso'] == true) {
        _mostrarSnack('✅ Plano cadastrado com sucesso!');
        _carregarPlanos();
      } else {
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Falha ao cadastrar.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _atualizarPlanoAPI(int id, String nome, String descricao, double preco, int ordem) async {
    try {
      final response = await http.put(
        Uri.parse('$_apiUrl/$id'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({'nome': nome, 'descricao': descricao, 'preco': preco, 'ordem': ordem}),
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('✅ Plano atualizado com sucesso!');
        _carregarPlanos();
      } else {
        _mostrarSnack('Erro ao atualizar plano.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _removerPlanoAPI(int id) async {
    try {
      final response = await http.delete(Uri.parse('$_apiUrl/$id'), headers: AppConfig.adminHeaders);
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('🗑️ Plano removido!');
        _carregarPlanos();
      } else {
        _mostrarSnack('Erro ao remover plano.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  void _abrirDialogoPlano({Map<String, dynamic>? planoExistente}) {
    final bool editando = planoExistente != null;
    final nomeCtrl = TextEditingController(text: planoExistente?['nome'] ?? '');
    final descricaoCtrl = TextEditingController(text: planoExistente?['descricao'] ?? '');
    final precoCtrl = TextEditingController(
      text: planoExistente != null ? (double.tryParse('${planoExistente['preco']}') ?? 0).toStringAsFixed(2) : '',
    );
    final ordemCtrl = TextEditingController(text: '${planoExistente?['ordem'] ?? 0}');

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardDark,
        title: Text(
          editando ? 'EDITAR PLANO' : 'NOVO PLANO DE ASSINATURA',
          style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nomeCtrl,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(labelText: 'Nome do Plano', labelStyle: TextStyle(color: Colors.grey)),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: descricaoCtrl,
                maxLines: 2,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(labelText: 'Descrição (aparece no site)', labelStyle: TextStyle(color: Colors.grey)),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: precoCtrl,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(labelText: 'Preço mensal (Ex: 99.90)', labelStyle: TextStyle(color: Colors.grey)),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: ordemCtrl,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  labelText: 'Ordem de exibição (0 = primeiro)',
                  labelStyle: TextStyle(color: Colors.grey),
                ),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
            onPressed: () {
              final preco = double.tryParse(precoCtrl.text.trim().replaceAll(',', '.'));
              final ordem = int.tryParse(ordemCtrl.text.trim()) ?? 0;
              if (nomeCtrl.text.trim().isNotEmpty && preco != null) {
                Navigator.pop(ctx);
                if (editando) {
                  _atualizarPlanoAPI(planoExistente!['id'] as int, nomeCtrl.text.trim(), descricaoCtrl.text.trim(), preco, ordem);
                } else {
                  _cadastrarPlanoAPI(nomeCtrl.text.trim(), descricaoCtrl.text.trim(), preco, ordem);
                }
              } else {
                _mostrarSnack('Preencha nome e um preço válido.');
              }
            },
            child: Text(editando ? 'Salvar Alterações' : 'Salvar', style: const TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('PLANOS DE ASSINATURA', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: Colors.white), onPressed: _carregarPlanos),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Novo Plano', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        onPressed: () => _abrirDialogoPlano(),
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _planos.isEmpty
              ? Center(child: Text('Nenhum plano cadastrado.', style: TextStyle(color: _textSecondary)))
              : RefreshIndicator(
                  onRefresh: _carregarPlanos,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 90), // Espaço extra embaixo para o FloatingActionButton
                    itemCount: _planos.length,
                    itemBuilder: (context, index) {
                      final p = _planos[index];
                      final double preco = double.tryParse(p['preco'].toString()) ?? 0;
                      final bool ativo = (p['ativo'] ?? 1).toString() == '1' || p['ativo'] == true;
                      final String descricao = (p['descricao'] ?? '').toString().trim();

                      return Container(
                        margin: const EdgeInsets.only(bottom: 14),
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                          color: _cardDark,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: ativo ? Colors.white12 : Colors.white10.withOpacity(0.3)),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            // Linha superior: Nome do plano e Preço sem cortes
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(
                                  child: Text(
                                    p['nome'] ?? '',
                                    style: TextStyle(
                                      color: ativo ? Colors.white : Colors.white38,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 16,
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Text(
                                  'R\$ ${preco.toStringAsFixed(2).replaceAll('.', ',')}/mês',
                                  style: TextStyle(
                                    color: _brandRed,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 15,
                                  ),
                                ),
                              ],
                            ),

                            // Descrição do plano (se houver)
                            if (descricao.isNotEmpty) ...[
                              const SizedBox(height: 8),
                              Text(
                                descricao,
                                style: TextStyle(color: _textSecondary, fontSize: 13, height: 1.3),
                              ),
                            ],

                            const SizedBox(height: 14),
                            const Divider(color: Colors.white10, height: 1),
                            const SizedBox(height: 10),

                            // Linha inferior: Status (se oculto) e Botões de Ação bem alinhados
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                if (!ativo)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                                    decoration: BoxDecoration(
                                      color: Colors.white10,
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: const Text('OCULTO NO SITE', style: TextStyle(color: Colors.white38, fontSize: 9, fontWeight: FontWeight.bold)),
                                  )
                                else
                                  const SizedBox.shrink(),

                                Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    IconButton(
                                      constraints: const BoxConstraints(),
                                      padding: const EdgeInsets.symmetric(horizontal: 8),
                                      icon: const Icon(Icons.edit_outlined, color: Colors.orangeAccent, size: 20),
                                      tooltip: 'Editar Plano',
                                      onPressed: () => _abrirDialogoPlano(planoExistente: p),
                                    ),
                                    const SizedBox(width: 8),
                                    IconButton(
                                      constraints: const BoxConstraints(),
                                      padding: const EdgeInsets.symmetric(horizontal: 8),
                                      icon: const Icon(Icons.delete_outline, color: Colors.white38, size: 20),
                                      tooltip: 'Remover Plano',
                                      onPressed: () => _removerPlanoAPI(p['id']),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}

// ==============================================================================
// TELA DETALHADA DE AGENDAMENTOS DO PROFISSIONAL
// ==============================================================================

class AgendaDetalhesScreen extends StatefulWidget {
  final Map<String, dynamic> barbeiro;
  final List<dynamic> agendamentos;
  final Function() onAtualizar;

  const AgendaDetalhesScreen({
    super.key,
    required this.barbeiro,
    required this.agendamentos,
    required this.onAtualizar,
  });

  @override
  State<AgendaDetalhesScreen> createState() => _AgendaDetalhesScreenState();
}

class _AgendaDetalhesScreenState extends State<AgendaDetalhesScreen> {
  final Color _bgColor = const Color(0xFF121212);
  final Color _cardColor = const Color(0xFF1E1E1E);
  final Color _brandRed = const Color(0xFFCF243E);
  final Color _textSecondary = const Color(0xFF9E9E9E);

  late List<dynamic> _listaAgendamentos;
  final String _baseUrl = AppConfig.apiUrl;

  @override
  void initState() {
    super.initState();
    _listaAgendamentos = List.from(widget.agendamentos);
  }

  Future<void> _marcarComoConcluido(int agendamentoId) async {
    try {
      final response = await http.post(
        Uri.parse('$_baseUrl/admin/agendamento/$agendamentoId/concluir'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        setState(() {
          _listaAgendamentos.removeWhere((a) => a['id'] == agendamentoId);
        });
        widget.onAtualizar();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Atendimento concluído e movido para o histórico!'), backgroundColor: Colors.teal),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Erro ao atualizar status.'), backgroundColor: Colors.red),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Erro de conexão com o servidor.'), backgroundColor: Colors.red),
      );
    }
  }

  Color _getStatusColor(String status) {
    switch (status.toLowerCase()) {
      case 'concluido':
      case 'finalizado': return Colors.tealAccent;
      case 'confirmado': return _brandRed;
      case 'cancelado': return Colors.grey;
      default: return Colors.amber;
    }
  }

  String _formatarDataSimples(String? dataStr) {
    if (dataStr == null || dataStr.length < 10) return '--/--/----';
    try {
      final partes = dataStr.substring(0, 10).split('-');
      if (partes.length == 3) {
        return '${partes[2]}/${partes[1]}/${partes[0]}';
      }
    } catch (_) {}
    return dataStr;
  }

  @override
  Widget build(BuildContext context) {
    final nomeBarbeiro = widget.barbeiro['nome'] ?? 'Profissional';

    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _cardColor,
        elevation: 0,
        title: Row(
          children: [
            _buildAvatarBarbeiro(widget.barbeiro['foto_url'], radius: 16),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                nomeBarbeiro,
                style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(16.0),
        child: _listaAgendamentos.isEmpty
            ? Center(
                child: Text(
                  'Nenhum atendimento detalhado para $nomeBarbeiro.',
                  style: TextStyle(color: _textSecondary, fontSize: 14),
                ),
              )
            : ListView.builder(
                itemCount: _listaAgendamentos.length,
                itemBuilder: (context, index) {
                  final ag = _listaAgendamentos[index];
                  final statusAtual = (ag['status'] ?? 'confirmado').toString().toLowerCase();
                  final statusColor = _getStatusColor(ag['status'] ?? 'Confirmado');
                  final podeConcluir = statusAtual != 'concluido' && statusAtual != 'finalizado' && statusAtual != 'cancelado';

                  return Container(
                    margin: const EdgeInsets.only(bottom: 16),
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: _cardColor,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Row(
                              children: [
                                const Icon(Icons.calendar_today, color: Colors.amber, size: 16),
                                const SizedBox(width: 8),
                                Text(
                                  '📅 ${_formatarDataSimples(ag['data'])}',
                                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
                                ),
                              ],
                            ),
                            Row(
                              children: [
                                const Icon(Icons.access_time, color: Colors.amber, size: 16),
                                const SizedBox(width: 6),
                                Text(
                                  '⏰ ${ag['horario'] ?? '--:--'}',
                                  style: const TextStyle(color: Colors.amber, fontSize: 15, fontWeight: FontWeight.bold),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const Divider(color: Colors.white24, height: 20),
                        Text('👤 Cliente: ${ag['cliente_nome'] ?? 'Cliente'}', style: const TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.w600)),
                        const SizedBox(height: 6),
                        Text('📞 Telefone: ${ag['cliente_telefone'] ?? 'Não informado'}', style: TextStyle(color: _textSecondary, fontSize: 13)),
                        const SizedBox(height: 6),
                        Text('✂️ Serviço: ${ag['servico'] ?? 'Corte'}', style: TextStyle(color: _textSecondary, fontSize: 13)),
                        const SizedBox(height: 6),
                        Text('💳 Pagamento: ${ag['tipo_pagamento'] ?? 'presencial'}', style: TextStyle(color: _textSecondary, fontSize: 13)),
                        const SizedBox(height: 14),
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                              decoration: BoxDecoration(
                                color: statusColor.withOpacity(0.15),
                                borderRadius: BorderRadius.circular(8),
                                border: Border.all(color: statusColor.withOpacity(0.4)),
                              ),
                              child: Text(
                                (ag['status'] ?? 'CONFIRMADO').toUpperCase(),
                                style: TextStyle(color: statusColor, fontSize: 11, fontWeight: FontWeight.bold),
                              ),
                            ),
                            const SizedBox(width: 8),
                            if (podeConcluir)
                              Expanded(
                                child: ElevatedButton.icon(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: Colors.teal,
                                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
                                  ),
                                  onPressed: () => showDialog(
                                    context: context,
                                    builder: (dialogCtx) => AlertDialog(
                                      backgroundColor: _cardColor,
                                      title: const Text('Concluir atendimento?', style: TextStyle(color: Colors.white, fontSize: 15)),
                                      content: Text(
                                        'Marcar o atendimento de ${ag['cliente_nome'] ?? 'cliente'} às ${ag['horario'] ?? ''} como concluído?',
                                        style: TextStyle(color: _textSecondary, fontSize: 13),
                                      ),
                                      actions: [
                                        TextButton(
                                          onPressed: () => Navigator.pop(dialogCtx),
                                          child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
                                        ),
                                        ElevatedButton(
                                          style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
                                          onPressed: () {
                                            Navigator.pop(dialogCtx);
                                            _marcarComoConcluido(ag['id']);
                                          },
                                          child: const Text('Concluir', style: TextStyle(color: Colors.white)),
                                        ),
                                      ],
                                    ),
                                  ),
                                  icon: const Icon(Icons.check, size: 16, color: Colors.white),
                                  label: const Text(
                                    'Marcar Concluído',
                                    style: TextStyle(color: Colors.white, fontSize: 12),
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                  );
                },
              ),
      ),
    );
  }
}

// Avatar reutilizável do barbeiro (foto base64/URL ou ícone padrão)
Widget _buildAvatarBarbeiro(dynamic foto, {double radius = 24}) {
  final String f = (foto ?? '').toString().trim();
  ImageProvider? img;
  if (f.startsWith('data:image')) {
    try {
      img = MemoryImage(base64Decode(f.split(',').last));
    } catch (_) {}
  } else if (f.startsWith('http')) {
    img = NetworkImage(f);
  }
  const Color vermelhoMarca = Color(0xFFE5243B);
  return CircleAvatar(
    radius: radius,
    backgroundColor: vermelhoMarca.withOpacity(0.2),
    backgroundImage: img,
    child: img == null ? const Icon(Icons.content_cut, color: vermelhoMarca) : null,
  );
}

class AgendaProfissionalScreen extends StatefulWidget {
  const AgendaProfissionalScreen({super.key});

  @override
  State<AgendaProfissionalScreen> createState() => _AgendaProfissionalScreenState();
}

class _AgendaProfissionalScreenState extends State<AgendaProfissionalScreen> {
  final Color _bgColor = const Color(0xFF121212);
  final Color _cardColor = const Color(0xFF1E1E1E);
  final Color _brandRed = const Color(0xFFCF243E);
  final Color _textSecondary = const Color(0xFF9E9E9E);

  List<dynamic> _barbeirosComAgenda = [];
  bool _isLoading = true;
  DateTime _dataSelecionada = DateTime.now();

  final String _baseUrl = AppConfig.apiUrl;

  @override
  void initState() {
    super.initState();
    _carregarAgendaGeral();
  }

  Future<void> _carregarAgendaGeral() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    
    final dataFormatada = "${_dataSelecionada.year}-${_dataSelecionada.month.toString().padLeft(2, '0')}-${_dataSelecionada.day.toString().padLeft(2, '0')}";

    try {
      final response = await http.get(
        Uri.parse('$_baseUrl/admin/agenda-equipe?data=$dataFormatada'),
        headers: AppConfig.adminHeaders,
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        final List<dynamic> equipe = data['equipe_agenda'] ?? [];

        // Garante a foto: busca na mesma rota usada pela tela "Equipe de Barbeiros"
        try {
          final respFotos = await http.get(
            Uri.parse('$_baseUrl/admin/barbeiros'),
            headers: AppConfig.adminHeaders,
          );
          if (respFotos.statusCode == 200) {
            final listaB = jsonDecode(respFotos.body)['barbeiros'] ?? [];
            final Map<String, String> fotos = {};
            for (final b in listaB) {
              fotos[b['id'].toString()] = (b['foto_url'] ?? '').toString();
            }
            for (final item in equipe) {
              final barb = item['barbeiro'];
              if (barb is Map) {
                final atual = (barb['foto_url'] ?? '').toString();
                if (atual.isEmpty) {
                  barb['foto_url'] = fotos[barb['id'].toString()] ?? '';
                }
              }
            }
          }
        } catch (e) {
          debugPrint('Erro ao buscar fotos dos barbeiros: $e');
        }

        if (mounted) {
          setState(() {
            _barbeirosComAgenda = equipe;
            _isLoading = false;
          });
        }
      } else {
        if (mounted) setState(() => _isLoading = false);
      }
    } catch (e) {
      debugPrint('Erro ao carregar agenda geral: $e');
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _selecionarData(BuildContext context) async {
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: _dataSelecionada,
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(
              primary: _brandRed,
              onSurface: Colors.white,
            ),
          ),
          child: child!,
        );
      },
    );
    if (picked != null && picked != _dataSelecionada) {
      setState(() {
        _dataSelecionada = picked;
      });
      _carregarAgendaGeral();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _cardColor,
        elevation: 0,
        title: Row(
          children: [
            Icon(Icons.event_seat, color: _brandRed, size: 20),
            const SizedBox(width: 8),
            const Expanded(
              child: Text(
                'AGENDA',
                style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: Icon(Icons.calendar_month, color: _brandRed, size: 22),
            tooltip: 'Selecionar Data',
            onPressed: () => _selecionarData(context),
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70, size: 22),
            tooltip: 'Atualizar Agenda',
            onPressed: _carregarAgendaGeral,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.person_add_alt_1),
        label: const Text('Agendar cliente'),
        onPressed: () async {
          final ok = await Navigator.push<bool>(
            context,
            MaterialPageRoute(builder: (context) => AgendarClienteScreen(dataInicial: _dataSelecionada)),
          );
          if (ok == true) _carregarAgendaGeral();
        },
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _barbeirosComAgenda.isEmpty
              ? Center(
                  child: Text(
                    'Nenhum profissional encontrado para esta data.',
                    style: TextStyle(color: _textSecondary, fontSize: 14),
                  ),
                )
              : RefreshIndicator(
                  onRefresh: _carregarAgendaGeral,
                  color: _brandRed,
                  child: ListView.builder(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 90),
                    itemCount: _barbeirosComAgenda.length,
                    itemBuilder: (context, index) {
                      final itemGrupo = _barbeirosComAgenda[index];
                      final barbeiro = itemGrupo['barbeiro'];
                      final List<dynamic> agendamentos = itemGrupo['agendamentos'];

                      return Padding(
                        padding: const EdgeInsets.only(bottom: 20),
                        child: InkWell(
                        onTap: () {
                          Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (context) => AgendaDetalhesScreen(
                                barbeiro: barbeiro,
                                agendamentos: agendamentos,
                                onAtualizar: _carregarAgendaGeral,
                              ),
                            ),
                          );
                        },
                        borderRadius: BorderRadius.circular(16),
                        child: Container(
                          decoration: BoxDecoration(
                            color: _cardColor,
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(color: Colors.white.withOpacity(0.05)),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Row(
                              children: [
                                _buildAvatarBarbeiro(barbeiro['foto_url'], radius: 24),
                                const SizedBox(width: 14),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        barbeiro['nome'] ?? 'Barbeiro',
                                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        barbeiro['cargo'] ?? 'Profissional',
                                        style: TextStyle(color: _brandRed, fontSize: 12, fontWeight: FontWeight.w600),
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Container(
                                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                  decoration: BoxDecoration(
                                    color: Colors.white.withOpacity(0.05),
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(Icons.event, color: _textSecondary, size: 14),
                                      const SizedBox(width: 4),
                                      Text(
                                        '${agendamentos.length}',
                                        style: TextStyle(color: _textSecondary, fontSize: 12, fontWeight: FontWeight.bold),
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 4),
                                const Icon(Icons.arrow_forward_ios, color: Colors.white54, size: 14),
                              ],
                            ),
                          ),
                        ),
                      ),
                      );
                    },
                  ),
                ),
    );
  }
}

// ==============================================================================
// GERENCIAR BARBEIROS
// ==============================================================================

class GerenciarBarbeirosScreen extends StatefulWidget {
  const GerenciarBarbeirosScreen({super.key});

  @override
  State<GerenciarBarbeirosScreen> createState() => _GerenciarBarbeirosScreenState();
}

class _GerenciarBarbeirosScreenState extends State<GerenciarBarbeirosScreen> {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  List<dynamic> _barbeiros = [];
  bool _isLoading = true;

  final String _apiUrl = '${AppConfig.apiUrl}/admin/barbeiros';

  @override
  void initState() {
    super.initState();
    _carregarBarbeiros();
  }

  Future<void> _carregarBarbeiros() async {
    if (!mounted) return;
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _barbeiros = data['barbeiros'] ?? [];
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
    }
  }

  Future<void> _cadastrarBarbeiroAPI(String nome, String cargo, String especialidade, String telefone, [String foto = '']) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome,
          'cargo': cargo,
          'especialidade': especialidade,
          'telefone': telefone,
          'foto_url': foto,
        }),
      );

      final resData = jsonDecode(response.body);
      if (!mounted) return;
      if (response.statusCode == 201 && resData['sucesso'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('✅ Barbeiro cadastrado no banco com sucesso!')),
        );
        _carregarBarbeiros();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('❌ Erro: ${resData['mensagem'] ?? 'Falha ao cadastrar.'}')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Erro de conexão com o servidor.')),
      );
    }
  }

  Future<void> _deletarBarbeiroAPI(int barbeiroId) async {
    try {
      final response = await http.delete(
        Uri.parse('$_apiUrl/$barbeiroId'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('🗑️ Barbeiro removido com sucesso!')),
        );
        _carregarBarbeiros();
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Erro ao remover barbeiro.')),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Erro de conexão com o servidor.')),
      );
    }
  }

  void _abrirDialogoNovoBarbeiro() {
    final nomeCtrl = TextEditingController();
    final cargoCtrl = TextEditingController();
    final especCtrl = TextEditingController();
    final foneCtrl = TextEditingController();
    String fotoBase64 = '';

    showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setStateDialog) {
          Uint8List? fotoBytes;
          if (fotoBase64.startsWith('data:image')) {
            try {
              fotoBytes = base64Decode(fotoBase64.split(',').last);
            } catch (_) {}
          }

          Future<void> escolherFoto(ImageSource source) async {
            final picked = await ImagePicker().pickImage(
              source: source,
              imageQuality: 70,
              maxWidth: 800,
              maxHeight: 800,
            );
            if (picked == null) return;
            final bytes = await picked.readAsBytes();
            if (!ctx.mounted) return;
            setStateDialog(() => fotoBase64 = 'data:image/jpeg;base64,${base64Encode(bytes)}');
          }

          void abrirSeletorFoto() {
            showModalBottomSheet(
              context: ctx,
              backgroundColor: _cardDark,
              builder: (sheetCtx) => SafeArea(
                child: Wrap(
                  children: [
                    ListTile(
                      leading: const Icon(Icons.camera_alt, color: Colors.white),
                      title: const Text('Tirar Foto com a Câmera', style: TextStyle(color: Colors.white)),
                      onTap: () {
                        Navigator.pop(sheetCtx);
                        escolherFoto(ImageSource.camera);
                      },
                    ),
                    ListTile(
                      leading: const Icon(Icons.photo_library, color: Colors.white),
                      title: const Text('Escolher da Galeria', style: TextStyle(color: Colors.white)),
                      onTap: () {
                        Navigator.pop(sheetCtx);
                        escolherFoto(ImageSource.gallery);
                      },
                    ),
                    if (fotoBase64.isNotEmpty)
                      ListTile(
                        leading: const Icon(Icons.delete_outline, color: Colors.red),
                        title: const Text('Remover foto', style: TextStyle(color: Colors.red)),
                        onTap: () {
                          Navigator.pop(sheetCtx);
                          setStateDialog(() => fotoBase64 = '');
                        },
                      ),
                  ],
                ),
              ),
            );
          }

          return AlertDialog(
            backgroundColor: _cardDark,
            title: const Text(
              'CADASTRAR NOVO BARBEIRO',
              style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  GestureDetector(
                    onTap: abrirSeletorFoto,
                    child: CircleAvatar(
                      radius: 40,
                      backgroundColor: _brandRed.withOpacity(0.2),
                      backgroundImage: fotoBytes != null ? MemoryImage(fotoBytes) : null,
                      child: fotoBytes == null ? Icon(Icons.add_a_photo, color: _brandRed, size: 30) : null,
                    ),
                  ),
                  TextButton.icon(
                    onPressed: abrirSeletorFoto,
                    icon: const Icon(Icons.upload, size: 18, color: Colors.white70),
                    label: Text(
                      fotoBytes == null ? 'Adicionar foto (opcional)' : 'Trocar foto',
                      style: const TextStyle(color: Colors.white70),
                    ),
                  ),
                  const SizedBox(height: 4),
                  TextField(
                    controller: nomeCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Nome do Barbeiro',
                      labelStyle: TextStyle(color: Colors.grey),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: cargoCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Cargo / Título (Ex: Barbeiro Master)',
                      labelStyle: TextStyle(color: Colors.grey),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: especCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Especialidade (Ex: Cortes e Barba)',
                      labelStyle: TextStyle(color: Colors.grey),
                    ),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: foneCtrl,
                    keyboardType: TextInputType.phone,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Telefone / WhatsApp',
                      labelStyle: TextStyle(color: Colors.grey),
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
              ),
              ElevatedButton(
                style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
                onPressed: () {
                  final nome = nomeCtrl.text.trim();
                  if (nome.isNotEmpty) {
                    final cargo = cargoCtrl.text.trim().isEmpty ? 'Barbeiro' : cargoCtrl.text.trim();
                    final espec = especCtrl.text.trim().isEmpty ? 'Cortes em Geral' : especCtrl.text.trim();
                    final fone = foneCtrl.text.trim().isEmpty ? '-' : foneCtrl.text.trim();

                    Navigator.pop(ctx);
                    _cadastrarBarbeiroAPI(nome, cargo, espec, fone, fotoBase64);
                  }
                },
                child: const Text('Salvar', style: TextStyle(color: Colors.white)),
              ),
            ],
          );
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text(
          'EQUIPE DE BARBEIROS',
          style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white),
            onPressed: _carregarBarbeiros,
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Novo Barbeiro', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
        onPressed: _abrirDialogoNovoBarbeiro,
      ),
      body: _isLoading
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : _barbeiros.isEmpty
              ? Center(
                  child: Text('Nenhum barbeiro cadastrado.', style: TextStyle(color: _textSecondary)),
                )
              : ListView.builder(
                  padding: const EdgeInsets.all(16),
  itemCount: _barbeiros.length,
                  itemBuilder: (context, index) {
                    final b = _barbeiros[index];
                    final String fotoUrl = (b['foto_url'] ?? '').toString();
                    final bool exibirAgenda = (b['exibir_agenda'] == null) ? true : (b['exibir_agenda'] == 1 || b['exibir_agenda'] == true);
                    return Container(
                      margin: const EdgeInsets.only(bottom: 12),
                      decoration: BoxDecoration(
                        color: _cardDark,
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(color: Colors.white10),
                      ),
                      child: Material(
                        color: Colors.transparent,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: () async {
                            await Navigator.push(
                              context,
                              MaterialPageRoute(builder: (context) => EditarBarbeiroScreen(barbeiro: b)),
                            );
                            _carregarBarbeiros();
                          },
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Row(
                              children: [
                                CircleAvatar(
                                  radius: 24,
                                  backgroundColor: _brandRed.withOpacity(0.2),
                                  backgroundImage: fotoUrl.startsWith('data:image')
                                      ? MemoryImage(base64Decode(fotoUrl.split(',').last))
                                      : null,
                                  child: fotoUrl.startsWith('data:image')
                                      ? null
                                      : Icon(Icons.content_cut, color: _brandRed, size: 24),
                                ),
                                const SizedBox(width: 14),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        b['nome'] ?? '',
                                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 16),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        b['cargo'] ?? '',
                                        style: TextStyle(color: _brandRed, fontSize: 12, fontWeight: FontWeight.bold),
                                      ),
                                      const SizedBox(height: 4),
                                      Text(
                                        b['especialidade'] ?? '',
                                        style: TextStyle(color: _textSecondary, fontSize: 12),
                                      ),
                                      if (!exibirAgenda) ...[
                                        const SizedBox(height: 4),
                                        Text(
                                          'Não exibido na agenda',
                                          style: TextStyle(color: Colors.white38, fontSize: 11, fontStyle: FontStyle.italic),
                                        ),
                                      ],
                                    ],
                                  ),
                                ),
                                const Icon(Icons.chevron_right, color: Colors.white24),
                                IconButton(
                                  icon: const Icon(Icons.delete_outline, color: Colors.white38),
                                  onPressed: () {
                                    _deletarBarbeiroAPI(b['id']);
                                  },
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                ),
    );
  }
}

// ==============================================================================
// TELA DE EDIÇÃO DO COLABORADOR (Dados gerais / Comissões / Horários)
// Inspirada no fluxo de gestão de equipe usado por apps de barbearia do mercado.
// ==============================================================================

class EditarBarbeiroScreen extends StatefulWidget {
  final Map<String, dynamic> barbeiro;

  const EditarBarbeiroScreen({super.key, required this.barbeiro});

  @override
  State<EditarBarbeiroScreen> createState() => _EditarBarbeiroScreenState();
}

class _EditarBarbeiroScreenState extends State<EditarBarbeiroScreen> with SingleTickerProviderStateMixin {
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);
  final Color _brandGreen = const Color(0xFF34C759);

  late TabController _tabController;

  late TextEditingController _nomeCtrl;
  late TextEditingController _apelidoCtrl;
  late TextEditingController _emailCtrl;
  late TextEditingController _telefoneCtrl;
  late TextEditingController _cargoCtrl;
  late TextEditingController _especialidadeCtrl;

  String _nivelAcesso = 'Atendente';
  bool _exibirAgenda = true;
  bool _verTodasAgendas = false;
  String _fotoBase64 = '';
  bool _salvandoDados = false;

  final List<String> _niveisAcesso = const ['Atendente', 'Barbeiro', 'Gerente', 'Administrador'];

  String get _apiUrlBarbeiro => '${AppConfig.apiUrl}/admin/barbeiros/${widget.barbeiro['id']}';
  String get _apiUrlComissoes => '${AppConfig.apiUrl}/admin/barbeiro/${widget.barbeiro['id']}/comissoes';
  String get _apiUrlHorarios => '${AppConfig.apiUrl}/admin/barbeiro/${widget.barbeiro['id']}/horarios';

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 3, vsync: this);

    final b = widget.barbeiro;
    _nomeCtrl = TextEditingController(text: b['nome'] ?? '');
    _apelidoCtrl = TextEditingController(text: b['apelido'] ?? '');
    _emailCtrl = TextEditingController(text: b['email'] ?? '');
    _telefoneCtrl = TextEditingController(text: b['telefone'] ?? '');
    _cargoCtrl = TextEditingController(text: b['cargo'] ?? 'Barbeiro');
    _especialidadeCtrl = TextEditingController(text: b['especialidade'] ?? 'Cortes em Geral');
    _nivelAcesso = _niveisAcesso.contains(b['nivel_acesso']) ? b['nivel_acesso'] : 'Atendente';
    _exibirAgenda = (b['exibir_agenda'] == null) ? true : (b['exibir_agenda'] == 1 || b['exibir_agenda'] == true);
    _verTodasAgendas = (b['ver_todas_agendas'] == 1 || b['ver_todas_agendas'] == true);
    _fotoBase64 = (b['foto_url'] ?? '').toString();
  }

  @override
  void dispose() {
    _tabController.dispose();
    _nomeCtrl.dispose();
    _apelidoCtrl.dispose();
    _emailCtrl.dispose();
    _telefoneCtrl.dispose();
    _cargoCtrl.dispose();
    _especialidadeCtrl.dispose();
    super.dispose();
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _selecionarImagem(ImageSource source) async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(source: source, imageQuality: 70, maxWidth: 800, maxHeight: 800);
    if (pickedFile != null) {
      final bytes = await pickedFile.readAsBytes();
      setState(() {
        _fotoBase64 = 'data:image/jpeg;base64,${base64Encode(bytes)}';
      });
    }
  }

  void _abrirSeletorImagem() {
    showModalBottomSheet(
      context: context,
      backgroundColor: _cardDark,
      builder: (_) => SafeArea(
        child: Wrap(
          children: [
            ListTile(
              leading: const Icon(Icons.camera_alt, color: Colors.white),
              title: const Text('Tirar Foto com a Câmera', style: TextStyle(color: Colors.white)),
              onTap: () {
                Navigator.pop(context);
                _selecionarImagem(ImageSource.camera);
              },
            ),
            ListTile(
              leading: const Icon(Icons.photo_library, color: Colors.white),
              title: const Text('Escolher da Galeria', style: TextStyle(color: Colors.white)),
              onTap: () {
                Navigator.pop(context);
                _selecionarImagem(ImageSource.gallery);
              },
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _salvarDadosGerais() async {
    final nome = _nomeCtrl.text.trim();
    if (nome.isEmpty) {
      _mostrarSnack('O nome é obrigatório.');
      return;
    }
    setState(() => _salvandoDados = true);
    try {
      final response = await http.put(
        Uri.parse(_apiUrlBarbeiro),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome,
          'apelido': _apelidoCtrl.text.trim(),
          'email': _emailCtrl.text.trim(),
          'telefone': _telefoneCtrl.text.trim(),
          'cargo': _cargoCtrl.text.trim().isEmpty ? 'Barbeiro' : _cargoCtrl.text.trim(),
          'especialidade': _especialidadeCtrl.text.trim().isEmpty ? 'Cortes em Geral' : _especialidadeCtrl.text.trim(),
          'nivel_acesso': _nivelAcesso,
          'foto_url': _fotoBase64,
          'exibir_agenda': _exibirAgenda,
          'ver_todas_agendas': _verTodasAgendas,
        }),
      );
      if (!mounted) return;
      final resData = jsonDecode(response.body);
      if (response.statusCode == 200 && resData['sucesso'] == true) {
        _mostrarSnack('✅ Dados salvos com sucesso!');
      } else {
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Erro ao salvar.'}');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    } finally {
      if (mounted) setState(() => _salvandoDados = false);
    }
  }

  Future<void> _excluirColaborador() async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardDark,
        title: const Text('Remover colaborador?', style: TextStyle(color: Colors.white)),
        content: Text('O colaborador sai da agenda e do site, e os agendamentos futuros dele serão cancelados. O histórico financeiro é mantido.', style: TextStyle(color: _textSecondary)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar', style: TextStyle(color: Colors.grey))),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Remover', style: TextStyle(color: Colors.red))),
        ],
      ),
    );
    if (confirmar != true) return;
    try {
      final response = await http.delete(Uri.parse(_apiUrlBarbeiro), headers: AppConfig.adminHeaders);
      if (!mounted) return;
      if (response.statusCode == 200) {
        Navigator.pop(context);
      } else {
        _mostrarSnack('Erro ao remover colaborador.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: Text(
          widget.barbeiro['nome'] ?? 'Colaborador',
          style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
        ),
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: _brandRed,
          labelColor: Colors.white,
          unselectedLabelColor: _textSecondary,
          tabs: const [
            Tab(text: 'Dados gerais'),
            Tab(text: 'Comissões'),
            Tab(text: 'Horários'),
          ],
        ),
      ),
      body: TabBarView(
        controller: _tabController,
        children: [
          _buildAbaDadosGerais(),
          _AbaComissoes(
            apiUrl: _apiUrlComissoes,
            cardDark: _cardDark,
            brandRed: _brandRed,
            brandGreen: _brandGreen,
            textSecondary: _textSecondary,
          ),
          _AbaHorarios(
            apiUrl: _apiUrlHorarios,
            cardDark: _cardDark,
            brandRed: _brandRed,
            brandGreen: _brandGreen,
            textSecondary: _textSecondary,
          ),
        ],
      ),
    );
  }

  Widget _buildAbaDadosGerais() {
    Uint8List? imagemBytes = _fotoBase64.startsWith('data:image') ? base64Decode(_fotoBase64.split(',').last) : null;

    InputDecoration _dec(String label) => InputDecoration(
          labelText: label,
          labelStyle: TextStyle(color: _textSecondary),
          enabledBorder: OutlineInputBorder(borderSide: BorderSide(color: Colors.white10), borderRadius: BorderRadius.circular(8)),
          focusedBorder: OutlineInputBorder(borderSide: BorderSide(color: _brandRed), borderRadius: BorderRadius.circular(8)),
        );

    return SingleChildScrollView(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Center(
            child: Column(
              children: [
                GestureDetector(
                  onTap: _abrirSeletorImagem,
                  child: CircleAvatar(
                    radius: 44,
                    backgroundColor: _brandRed.withOpacity(0.2),
                    backgroundImage: imagemBytes != null ? MemoryImage(imagemBytes) : null,
                    child: imagemBytes == null ? Icon(Icons.person, color: _brandRed, size: 44) : null,
                  ),
                ),
                const SizedBox(height: 8),
                TextButton.icon(
                  onPressed: _abrirSeletorImagem,
                  icon: const Icon(Icons.upload, size: 18, color: Colors.white70),
                  label: const Text('Selecionar imagem', style: TextStyle(color: Colors.white70)),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          TextField(controller: _nomeCtrl, style: const TextStyle(color: Colors.white), decoration: _dec('Nome')),
          const SizedBox(height: 12),
          TextField(controller: _apelidoCtrl, style: const TextStyle(color: Colors.white), decoration: _dec('Apelido (exibido na agenda, opcional)')),
          const SizedBox(height: 12),
          TextField(controller: _emailCtrl, style: const TextStyle(color: Colors.white), keyboardType: TextInputType.emailAddress, decoration: _dec('Email')),
          const SizedBox(height: 12),
          TextField(controller: _telefoneCtrl, style: const TextStyle(color: Colors.white), keyboardType: TextInputType.phone, decoration: _dec('Telefone / WhatsApp')),
          const SizedBox(height: 12),
          TextField(controller: _cargoCtrl, style: const TextStyle(color: Colors.white), decoration: _dec('Cargo / Título (Ex: Barbeiro Master)')),
          const SizedBox(height: 12),
          TextField(controller: _especialidadeCtrl, style: const TextStyle(color: Colors.white), decoration: _dec('Especialidade (Ex: Cortes e Barba)')),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: _cardDark, borderRadius: BorderRadius.circular(10), border: Border.all(color: Colors.white10)),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('ACESSO', style: TextStyle(color: _textSecondary, fontSize: 12, fontWeight: FontWeight.bold)),
                const SizedBox(height: 6),
                DropdownButtonFormField<String>(
                  value: _nivelAcesso,
                  dropdownColor: _cardDark,
                  style: const TextStyle(color: Colors.white),
                  decoration: const InputDecoration(border: InputBorder.none),
                  items: _niveisAcesso
                      .map((nivel) => DropdownMenuItem(value: nivel, child: Text(nivel)))
                      .toList(),
                  onChanged: (v) => setState(() => _nivelAcesso = v ?? 'Atendente'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
            decoration: BoxDecoration(
              color: _cardDark,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: Colors.white10),
            ),
            child: Material( // <--- ENVOLVA NUM WIDGET MATERIAL PARA CORRIGIR O ERRO
              color: Colors.transparent,
              child: Column(
                children: [
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    activeThumbColor: _brandGreen,
                    title: const Text('Exibir na Agenda', style: TextStyle(color: Colors.white)),
                    value: _exibirAgenda,
                    onChanged: (v) => setState(() => _exibirAgenda = v),
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    activeThumbColor: _brandGreen,
                    title: const Text('Ver Todas as Agendas', style: TextStyle(color: Colors.white)),
                    value: _verTodasAgendas,
                    onChanged: (v) => setState(() => _verTodasAgendas = v),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: _brandRed, padding: const EdgeInsets.symmetric(vertical: 14)),
              onPressed: _salvandoDados ? null : _salvarDadosGerais,
              child: _salvandoDados
                  ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Salvar', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(side: const BorderSide(color: Colors.red), padding: const EdgeInsets.symmetric(vertical: 14)),
              onPressed: _excluirColaborador,
              child: const Text('Excluir colaborador', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
            ),
          ),
        ],
      ),
    );
  }
}

// ==============================================================================
// ABA "COMISSÕES" CORRIGIDA COM AUTENTICAÇÃO E TRATAMENTO DE ERROS
// ==============================================================================

class _AbaComissoes extends StatefulWidget {
  final String apiUrl;
  final Color cardDark;
  final Color brandRed;
  final Color brandGreen;
  final Color textSecondary;

  const _AbaComissoes({
    required this.apiUrl,
    required this.cardDark,
    required this.brandRed,
    required this.brandGreen,
    required this.textSecondary,
  });

  @override
  State<_AbaComissoes> createState() => _AbaComissoesState();
}

class _AbaComissoesState extends State<_AbaComissoes> with SingleTickerProviderStateMixin {
  late TabController _subTabController;
  bool _isLoading = true;
  bool _salvando = false;
  String _busca = '';

  List<Map<String, dynamic>> _servicos = [];
  List<Map<String, dynamic>> _produtos = [];

  final Map<int, TextEditingController> _duracaoCtrls = {};
  final Map<int, TextEditingController> _precoCtrls = {};
  final Map<int, TextEditingController> _comissaoServicoCtrls = {};
  final Map<int, TextEditingController> _comissaoProdutoCtrls = {};

  @override
  void initState() {
    super.initState();
    _subTabController = TabController(length: 2, vsync: this);
    _carregar();
  }

  @override
  void dispose() {
    _subTabController.dispose();
    for (final c in _duracaoCtrls.values) c.dispose();
    for (final c in _precoCtrls.values) c.dispose();
    for (final c in _comissaoServicoCtrls.values) c.dispose();
    for (final c in _comissaoProdutoCtrls.values) c.dispose();
    super.dispose();
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _carregar() async {
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(widget.apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        _servicos = List<Map<String, dynamic>>.from(data['servicos'] ?? []);
        _produtos = List<Map<String, dynamic>>.from(data['produtos'] ?? []);

        for (final s in _servicos) {
          final id = s['id'] as int;
          _duracaoCtrls[id] = TextEditingController(text: '${s['duracao_minutos'] ?? 30}');
          _precoCtrls[id] = TextEditingController(
            text: (double.tryParse('${s['preco_personalizado']}') ?? 0).toStringAsFixed(2),
          );
          _comissaoServicoCtrls[id] = TextEditingController(
            text: (double.tryParse('${s['comissao_percentual']}') ?? 40).toStringAsFixed(2),
          );
        }
        for (final p in _produtos) {
          final id = p['id'] as int;
          _comissaoProdutoCtrls[id] = TextEditingController(
            text: (double.tryParse('${p['comissao_percentual'] ?? 20}') ?? 20).toStringAsFixed(2),
          );
        }
        setState(() => _isLoading = false);
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar comissões.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  void _ativarTodosServicos() {
    setState(() {
      for (final s in _servicos) {
        s['realiza'] = 1;
      }
    });
  }

  Future<void> _salvarAlteracoes() async {
    setState(() => _salvando = true);
    try {
      for (final s in _servicos) {
        final id = s['id'] as int;
        await http.post(
          Uri.parse(widget.apiUrl),
          headers: AppConfig.adminHeaders,
          body: jsonEncode({
            'tipo': 'servico',
            'item_id': id,
            'realiza': (s['realiza'] == 1 || s['realiza'] == true),
            'duracao_minutos': int.tryParse(_duracaoCtrls[id]?.text ?? '') ?? 30,
            'preco_personalizado': double.tryParse((_precoCtrls[id]?.text ?? '0').replaceAll(',', '.')) ?? 0,
            'comissao_percentual': double.tryParse((_comissaoServicoCtrls[id]?.text ?? '0').replaceAll(',', '.')) ?? 40,
          }),
        );
      }
      for (final p in _produtos) {
        final id = p['id'] as int;
        await http.post(
          Uri.parse(widget.apiUrl),
          headers: AppConfig.adminHeaders,
          body: jsonEncode({
            'tipo': 'produto',
            'item_id': id,
            'comissao_percentual': double.tryParse((_comissaoProdutoCtrls[id]?.text ?? '0').replaceAll(',', '.')) ?? 20,
          }),
        );
      }
      if (!mounted) return;
      _mostrarSnack('✅ Comissões atualizadas com sucesso!');
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('❌ Erro ao salvar alterações.');
    } finally {
      if (mounted) setState(() => _salvando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Center(child: CircularProgressIndicator(color: widget.brandRed));
    }

    final servicosFiltrados = _busca.trim().isEmpty
        ? _servicos
        : _servicos.where((s) => (s['nome'] ?? '').toString().toLowerCase().contains(_busca.toLowerCase())).toList();

    return Column(
      children: [
        TabBar(
          controller: _subTabController,
          indicatorColor: widget.brandRed,
          labelColor: Colors.white,
          unselectedLabelColor: widget.textSecondary,
          tabs: [
            Tab(text: 'Serviços (${_servicos.length})'),
            Tab(text: 'Produtos (${_produtos.length})'),
          ],
        ),
        Expanded(
          child: TabBarView(
            controller: _subTabController,
            children: [
              Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: TextField(
                      style: const TextStyle(color: Colors.white),
                      decoration: InputDecoration(
                        hintText: 'Buscar serviço...',
                        hintStyle: TextStyle(color: widget.textSecondary),
                        prefixIcon: Icon(Icons.search, color: widget.textSecondary),
                        filled: true,
                        fillColor: widget.cardDark,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide.none),
                      ),
                      onChanged: (v) => setState(() => _busca = v),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    child: SizedBox(
                      width: double.infinity,
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(side: BorderSide(color: widget.brandGreen)),
                        onPressed: _ativarTodosServicos,
                        child: Text('Ativar todos os serviços', style: TextStyle(color: widget.brandGreen)),
                      ),
                    ),
                  ),
                  Expanded(
                    child: ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: servicosFiltrados.length,
                      itemBuilder: (context, index) {
                        final s = servicosFiltrados[index];
                        final id = s['id'] as int;
                        final bool realiza = (s['realiza'] == 1 || s['realiza'] == true);
                        return Container(
                          margin: const EdgeInsets.only(bottom: 10),
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: widget.cardDark,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: Colors.white10),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('${s['nome'] ?? ''}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
                              Text(
                                'Padrão do serviço: R\$ ${(double.tryParse('${s['preco_padrao']}') ?? 0).toStringAsFixed(2)}',
                                style: TextStyle(color: widget.textSecondary, fontSize: 12),
                              ),
                              const SizedBox(height: 10),
                              Row(
                                children: [
                                  Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    children: [
                                      Text('REALIZA', style: TextStyle(color: widget.textSecondary, fontSize: 11)),
                                      Switch(
                                        value: realiza,
                                        activeColor: widget.brandGreen,
                                        onChanged: (v) => setState(() => s['realiza'] = v ? 1 : 0),
                                      ),
                                    ],
                                  ),
                                  const Spacer(),
                                  SizedBox(
                                    width: 90,
                                    child: TextField(
                                      controller: _duracaoCtrls[id],
                                      keyboardType: TextInputType.number,
                                      style: const TextStyle(color: Colors.white),
                                      textAlign: TextAlign.center,
                                      decoration: InputDecoration(
                                        labelText: 'Duração (min)',
                                        labelStyle: TextStyle(color: widget.textSecondary, fontSize: 10),
                                        border: const OutlineInputBorder(),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 10),
                              Row(
                                children: [
                                  Expanded(
                                    child: TextField(
                                      controller: _precoCtrls[id],
                                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                      style: const TextStyle(color: Colors.white),
                                      decoration: InputDecoration(
                                        labelText: 'Preço (R\$)',
                                        labelStyle: TextStyle(color: widget.textSecondary, fontSize: 11),
                                        border: const OutlineInputBorder(),
                                      ),
                                    ),
                                  ),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: TextField(
                                      controller: _comissaoServicoCtrls[id],
                                      keyboardType: const TextInputType.numberWithOptions(decimal: true),
                                      style: const TextStyle(color: Colors.white),
                                      decoration: InputDecoration(
                                        labelText: '% Comissão',
                                        labelStyle: TextStyle(color: widget.textSecondary, fontSize: 11),
                                        border: const OutlineInputBorder(),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                ],
              ),
              ListView.builder(
                padding: const EdgeInsets.all(12),
                itemCount: _produtos.length,
                itemBuilder: (context, index) {
                  final p = _produtos[index];
                  final id = p['id'] as int;
                  return Container(
                    margin: const EdgeInsets.only(bottom: 10),
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: widget.cardDark,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('${p['nome'] ?? ''}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
                              Text(
                                'R\$ ${(double.tryParse('${p['preco']}') ?? 0).toStringAsFixed(2)}',
                                style: TextStyle(color: widget.brandGreen, fontSize: 13),
                              ),
                            ],
                          ),
                        ),
                        SizedBox(
                          width: 90,
                          child: TextField(
                            controller: _comissaoProdutoCtrls[id],
                            keyboardType: const TextInputType.numberWithOptions(decimal: true),
                            style: const TextStyle(color: Colors.white),
                            textAlign: TextAlign.center,
                            decoration: InputDecoration(
                              labelText: '% Comissão',
                              labelStyle: TextStyle(color: widget.textSecondary, fontSize: 10),
                              border: const OutlineInputBorder(),
                            ),
                          ),
                        ),
                      ],
                    ),
                  );
                },
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: SizedBox(
            width: double.infinity,
            child: ElevatedButton.icon(
              style: ElevatedButton.styleFrom(backgroundColor: widget.brandRed, padding: const EdgeInsets.symmetric(vertical: 14)),
              onPressed: _salvando ? null : _salvarAlteracoes,
              icon: _salvando
                  ? const SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Icon(Icons.check, color: Colors.white),
              label: const Text('Salvar alterações', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ),
        ),
      ],
    );
  }
}

// ==============================================================================
// ABA "HORÁRIOS" CORRIGIDA COM AUTENTICAÇÃO
// ==============================================================================

class _AbaHorarios extends StatefulWidget {
  final String apiUrl;
  final Color cardDark;
  final Color brandRed;
  final Color brandGreen;
  final Color textSecondary;

  const _AbaHorarios({
    required this.apiUrl,
    required this.cardDark,
    required this.brandRed,
    required this.brandGreen,
    required this.textSecondary,
  });

  @override
  State<_AbaHorarios> createState() => _AbaHorariosState();
}

class _AbaHorariosState extends State<_AbaHorarios> {
  bool _isLoading = true;
  bool _salvando = false;
  List<Map<String, dynamic>> _dias = [];

  @override
  void initState() {
    super.initState();
    _carregar();
  }

  void _mostrarSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _carregar() async {
    setState(() => _isLoading = true);
    try {
      final response = await http.get(
        Uri.parse(widget.apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _dias = List<Map<String, dynamic>>.from(data['horarios'] ?? []);
          _isLoading = false;
        });
      } else {
        setState(() => _isLoading = false);
        _mostrarSnack('Erro ao carregar horários.');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _isLoading = false);
      _mostrarSnack('Erro de conexão com o servidor.');
    }
  }

  Future<void> _selecionarHora(Map<String, dynamic> dia, String campo) async {
    final partes = (dia[campo] ?? '09:00').toString().split(':');
    final horaAtual = TimeOfDay(
      hour: int.tryParse(partes[0]) ?? 9,
      minute: partes.length > 1 ? (int.tryParse(partes[1]) ?? 0) : 0,
    );
    final novaHora = await showTimePicker(context: context, initialTime: horaAtual);
    if (novaHora != null) {
      setState(() {
        dia[campo] = '${novaHora.hour.toString().padLeft(2, '0')}:${novaHora.minute.toString().padLeft(2, '0')}';
      });
    }
  }

  Future<void> _salvar() async {
    setState(() => _salvando = true);
    try {
      final response = await http.post(
        Uri.parse(widget.apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'dias': _dias
              .map((d) => {
                    'dia_semana': d['dia_semana'],
                    'trabalha': (d['trabalha'] == 1 || d['trabalha'] == true),
                    'hora_inicio': d['hora_inicio'],
                    'hora_fim': d['hora_fim'],
                    'almoco_inicio': d['almoco_inicio'],
                    'almoco_fim': d['almoco_fim'],
                  })
              .toList(),
        }),
      );
      if (!mounted) return;
      if (response.statusCode == 200) {
        _mostrarSnack('✅ Horários salvos com sucesso!');
      } else {
        _mostrarSnack('❌ Erro ao salvar horários.');
      }
    } catch (e) {
      if (!mounted) return;
      _mostrarSnack('Erro de conexão com o servidor.');
    } finally {
      if (mounted) setState(() => _salvando = false);
    }
  }

  Widget _campoHora(Map<String, dynamic> dia, String campo, String label) {
    return GestureDetector(
      onTap: () => _selecionarHora(dia, campo),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 10),
        decoration: BoxDecoration(
          color: Colors.black26,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: Colors.white10),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: TextStyle(color: widget.textSecondary, fontSize: 10)),
            Text('${dia[campo] ?? '--:--'}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_isLoading) {
      return Center(child: CircularProgressIndicator(color: widget.brandRed));
    }
    return Column(
      children: [
        Expanded(
          child: ListView.builder(
            padding: const EdgeInsets.all(12),
            itemCount: _dias.length,
            itemBuilder: (context, index) {
              final dia = _dias[index];
              final bool trabalha = (dia['trabalha'] == 1 || dia['trabalha'] == true);
              return Container(
                margin: const EdgeInsets.only(bottom: 10),
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: widget.cardDark,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white10),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text('${dia['nome_dia'] ?? ''}', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: trabalha ? widget.brandGreen.withOpacity(0.15) : Colors.white10,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Text(
                            trabalha ? 'Expediente' : 'Folga',
                            style: TextStyle(color: trabalha ? widget.brandGreen : widget.textSecondary, fontSize: 11, fontWeight: FontWeight.bold),
                          ),
                        ),
                        Switch(
                          value: trabalha,
                          activeColor: widget.brandGreen,
                          onChanged: (v) => setState(() => dia['trabalha'] = v ? 1 : 0),
                        ),
                      ],
                    ),
                    if (trabalha) ...[
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(child: _campoHora(dia, 'hora_inicio', 'JORNADA — INÍCIO')),
                          const SizedBox(width: 8),
                          Expanded(child: _campoHora(dia, 'hora_fim', 'JORNADA — FIM')),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Expanded(child: _campoHora(dia, 'almoco_inicio', 'ALMOÇO — INÍCIO')),
                          const SizedBox(width: 8),
                          Expanded(child: _campoHora(dia, 'almoco_fim', 'ALMOÇO — FIM')),
                        ],
                      ),
                    ],
                  ],
                ),
              );
            },
          ),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: widget.brandRed, padding: const EdgeInsets.symmetric(vertical: 14)),
              onPressed: _salvando ? null : _salvar,
              child: _salvando
                  ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Salvar', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ),
        ),
      ],
    );
  }
}

// ==============================================================================
// PAINEL DE COMISSÕES (período + colaborador + baixa de pagamento)
// ==============================================================================
class ComissoesScreen extends StatefulWidget {
  const ComissoesScreen({super.key});

  @override
  State<ComissoesScreen> createState() => _ComissoesScreenState();
}

class _ComissoesScreenState extends State<ComissoesScreen> {
  final Color _bgColor = const Color(0xFF121212);
  final Color _cardColor = const Color(0xFF1E1E1E);
  final Color _brandRed = const Color(0xFFCF243E);
  final Color _textSecondary = const Color(0xFF9E9E9E);

  late DateTime _inicio;
  late DateTime _fim;
  List<dynamic> _barbeiros = [];
  String? _barbeiroId; // null = todos os colaboradores
  String _situacao = 'todas'; // 'todas' | 'pendentes' | 'pagas'
  final Set<int> _selecionados = {};
  bool _carregando = true;
  bool _processando = false;
  String? _erro;
  Map<String, dynamic>? _dados;

  @override
  void initState() {
    super.initState();
    final hoje = DateTime.now();
    _inicio = DateTime(hoje.year, hoje.month, 1);
    _fim = DateTime(hoje.year, hoje.month, hoje.day);
    _carregarBarbeiros();
    _carregar();
  }

  String _fmtApi(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  String _fmtBr(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}/${d.year}';

  String _fmtBrIso(String iso) {
    final p = iso.split('-');
    return p.length == 3 ? '${p[2]}/${p[1]}' : iso;
  }

  double _num(dynamic v) => double.tryParse('${v ?? 0}') ?? 0;

  int _idDe(dynamic a) => int.tryParse('${a['id']}') ?? 0;

  String _moeda(double v) => 'R\$ ${v.toStringAsFixed(2).replaceAll('.', ',')}';

  String _pct(double v) => v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toStringAsFixed(1);

  dynamic _fotoDoBarbeiro(dynamic id) {
    for (final b in _barbeiros) {
      if (b['id'].toString() == id.toString()) return b['foto_url'];
    }
    return null;
  }

  void _snack(String msg, {bool erro = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: erro ? Colors.red : Colors.teal),
    );
  }

  Future<void> _carregarBarbeiros() async {
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiUrl}/admin/barbeiros'),
        headers: AppConfig.adminHeaders,
      );
      if (resp.statusCode == 200 && mounted) {
        final todos = jsonDecode(resp.body)['barbeiros'] ?? [];
        setState(() {
          _barbeiros = todos.where((b) => !(b['ativo'] == 0 || b['ativo'] == false)).toList();
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar barbeiros (comissões): $e');
    }
  }

  Future<void> _carregar() async {
    if (!mounted) return;
    setState(() {
      _carregando = true;
      _erro = null;
      _selecionados.clear();
    });
    try {
      final q = StringBuffer('inicio=${_fmtApi(_inicio)}&fim=${_fmtApi(_fim)}');
      if (_barbeiroId != null) q.write('&barbeiro_id=$_barbeiroId');
      final resp = await http.get(
        Uri.parse('${AppConfig.apiUrl}/admin/comissoes?$q'),
        headers: AppConfig.adminHeaders,
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        setState(() {
          _dados = jsonDecode(resp.body);
          _carregando = false;
        });
      } else {
        String msg = 'Erro ao carregar comissões.';
        try {
          msg = (jsonDecode(resp.body)['mensagem'] ?? msg).toString();
        } catch (_) {}
        setState(() {
          _erro = msg;
          _carregando = false;
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar comissões: $e');
      if (mounted) {
        setState(() {
          _erro = 'Erro de conexão com o servidor.';
          _carregando = false;
        });
      }
    }
  }

  void _definirPeriodo(DateTime i, DateTime f) {
    setState(() {
      _inicio = i;
      _fim = f;
    });
    _carregar();
  }

  Future<void> _escolherPeriodo() async {
    final r = await showDateRangePicker(
      context: context,
      firstDate: DateTime(2023),
      lastDate: DateTime(2030),
      initialDateRange: DateTimeRange(start: _inicio, end: _fim),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(primary: _brandRed, onSurface: Colors.white),
          ),
          child: child!,
        );
      },
    );
    if (r != null) _definirPeriodo(r.start, r.end);
  }

  Future<bool> _confirmar(String titulo, String texto, String botao) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardColor,
        title: Text(titulo, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        content: Text(texto, style: const TextStyle(color: Colors.white70, fontSize: 14)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed),
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(botao, style: const TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _enviarAcao(String rota, List<int> ids, String msgErro) async {
    setState(() => _processando = true);
    try {
      final resp = await http.post(
        Uri.parse('${AppConfig.apiUrl}/admin/comissoes/$rota'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({'agendamento_ids': ids}),
      );
      if (!mounted) return;
      String msg = msgErro;
      try {
        msg = (jsonDecode(resp.body)['mensagem'] ?? msgErro).toString();
      } catch (_) {}
      if (resp.statusCode == 200) {
        await _carregar();
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('✅ $msg'),
            backgroundColor: Colors.teal,
            action: rota == 'baixa'
                ? SnackBarAction(
                    label: 'VER PAGAS',
                    textColor: Colors.white,
                    onPressed: () => setState(() {
                      _situacao = 'pagas';
                      _selecionados.clear();
                    }),
                  )
                : null,
          ),
        );
      } else {
        _snack('❌ $msg', erro: true);
      }
    } catch (e) {
      debugPrint('Erro em comissões/$rota: $e');
      _snack('Erro de conexão com o servidor.', erro: true);
    } finally {
      if (mounted) setState(() => _processando = false);
    }
  }

  Future<void> _darBaixa(String nome, List<dynamic> alvo) async {
    if (alvo.isEmpty || _processando) return;
    final total = alvo.fold<double>(0, (s, a) => s + _num(a['comissao']));
    final ok = await _confirmar(
      'Dar baixa nas comissões?',
      'Confirmar o pagamento de ${_moeda(total)} para $nome (${alvo.length} atendimento(s))? '
          'Elas passam para "pagas".',
      'Dar baixa',
    );
    if (!ok) return;
    await _enviarAcao('baixa', alvo.map<int>((a) => _idDe(a)).toList(), 'Falha ao dar baixa.');
  }

  Future<void> _desfazerBaixa(dynamic atendimento) async {
    if (_processando) return;
    final ok = await _confirmar(
      'Desfazer baixa?',
      'Esta comissão (${_moeda(_num(atendimento['comissao']))}) volta para pendente.',
      'Desfazer',
    );
    if (!ok) return;
    await _enviarAcao('estornar', [_idDe(atendimento)], 'Falha ao desfazer a baixa.');
  }

  List<dynamic> _filtrarAtendimentos(List<dynamic> lista) {
    if (_situacao == 'pendentes') return lista.where((a) => a['pago'] != true).toList();
    if (_situacao == 'pagas') return lista.where((a) => a['pago'] == true).toList();
    return lista;
  }

  Widget _chipAtalho(String label, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ActionChip(
        label: Text(label, style: const TextStyle(color: Colors.white, fontSize: 12)),
        backgroundColor: _cardColor,
        side: const BorderSide(color: Colors.white10),
        onPressed: onTap,
      ),
    );
  }

  Widget _chipSituacao(String valor, String label) {
    final ativo = _situacao == valor;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label, style: TextStyle(color: ativo ? Colors.white : Colors.white70, fontSize: 12)),
        selected: ativo,
        selectedColor: _brandRed,
        backgroundColor: _cardColor,
        showCheckmark: false,
        onSelected: (_) => setState(() {
          _situacao = valor;
          _selecionados.clear();
        }),
      ),
    );
  }

  Widget _linhaResumo(String label, String valor, Color cor, {bool destaque = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Text(label, style: TextStyle(color: _textSecondary, fontSize: destaque ? 14 : 13)),
          ),
          Text(
            valor,
            style: TextStyle(color: cor, fontWeight: FontWeight.bold, fontSize: destaque ? 18 : 14),
          ),
        ],
      ),
    );
  }

  Widget _buildFiltros() {
    final valorAtual = _barbeiros.any((b) => b['id'].toString() == _barbeiroId) ? _barbeiroId : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
          onTap: _escolherPeriodo,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
            decoration: BoxDecoration(
              color: _cardColor,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: Colors.white10),
            ),
            child: Row(
              children: [
                Icon(Icons.date_range, color: _brandRed, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('PERÍODO', style: TextStyle(color: _textSecondary, fontSize: 10, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 2),
                      Text(
                        '${_fmtBr(_inicio)}  até  ${_fmtBr(_fim)}',
                        style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
                Icon(Icons.edit_calendar, color: _textSecondary, size: 18),
              ],
            ),
          ),
        ),
        const SizedBox(height: 10),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              _chipAtalho('Hoje', () {
                final h = DateTime.now();
                final d = DateTime(h.year, h.month, h.day);
                _definirPeriodo(d, d);
              }),
              _chipAtalho('7 dias', () {
                final h = DateTime.now();
                final d = DateTime(h.year, h.month, h.day);
                _definirPeriodo(d.subtract(const Duration(days: 6)), d);
              }),
              _chipAtalho('Este mês', () {
                final h = DateTime.now();
                _definirPeriodo(DateTime(h.year, h.month, 1), DateTime(h.year, h.month, h.day));
              }),
              _chipAtalho('Mês passado', () {
                final h = DateTime.now();
                _definirPeriodo(DateTime(h.year, h.month - 1, 1), DateTime(h.year, h.month, 0));
              }),
            ],
          ),
        ),
        const SizedBox(height: 10),
        DropdownButtonFormField<String?>(
          value: valorAtual,
          isExpanded: true,
          dropdownColor: _cardColor,
          style: const TextStyle(color: Colors.white, fontSize: 15),
          decoration: InputDecoration(
            labelText: 'Colaborador',
            labelStyle: TextStyle(color: _textSecondary),
            prefixIcon: Icon(Icons.person_outline, color: _brandRed),
            filled: true,
            fillColor: _cardColor,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
          ),
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('Todos os colaboradores')),
            ..._barbeiros.map<DropdownMenuItem<String?>>(
              (b) => DropdownMenuItem<String?>(
                value: b['id'].toString(),
                child: Text((b['nome'] ?? '').toString(), overflow: TextOverflow.ellipsis),
              ),
            ),
          ],
          onChanged: (v) {
            setState(() => _barbeiroId = v);
            _carregar();
          },
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            _chipSituacao('todas', 'Todas'),
            _chipSituacao('pendentes', 'Pendentes'),
            _chipSituacao('pagas', 'Pagas'),
          ],
        ),
      ],
    );
  }

  Widget _buildResumo() {
    final totalFat = _num(_dados?['total_faturamento']);
    final totalCom = _num(_dados?['total_comissao']);
    final paga = _num(_dados?['total_paga']);
    final pendente = _num(_dados?['total_pendente']);
    final cortes = (_dados?['total_cortes'] ?? 0).toString();

    int qtdPend = 0;
    int qtdPaga = 0;
    for (final g in ((_dados?['barbeiros'] ?? []) as List<dynamic>)) {
      for (final a in ((g['atendimentos'] ?? []) as List<dynamic>)) {
        if (a['pago'] == true) {
          qtdPaga++;
        } else {
          qtdPend++;
        }
      }
    }

    final List<Widget> linhas;
    if (_situacao == 'pendentes') {
      linhas = [
        _linhaResumo('Atendimentos pendentes', '$qtdPend', Colors.white),
        _linhaResumo('Comissões pendentes', _moeda(pendente), Colors.orangeAccent, destaque: true),
      ];
    } else if (_situacao == 'pagas') {
      linhas = [
        _linhaResumo('Atendimentos pagos', '$qtdPaga', Colors.white),
        _linhaResumo('Comissões pagas', _moeda(paga), Colors.greenAccent, destaque: true),
      ];
    } else {
      linhas = [
        _linhaResumo('Cortes finalizados', cortes, Colors.white),
        _linhaResumo('Faturamento', _moeda(totalFat), Colors.white),
        _linhaResumo('Comissões do período', _moeda(totalCom), Colors.white),
        _linhaResumo('Comissões pagas', _moeda(paga), Colors.greenAccent),
        _linhaResumo('Comissões pendentes', _moeda(pendente), Colors.orangeAccent, destaque: true),
        const Divider(color: Colors.white10, height: 16),
        _linhaResumo('Fica na barbearia', _moeda(totalFat - totalCom), Colors.greenAccent),
      ];
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _cardColor,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: (_situacao == 'pagas' ? Colors.greenAccent : Colors.orangeAccent).withOpacity(0.3)),
      ),
      child: Column(children: linhas),
    );
  }

  Widget _linhaAtendimento(dynamic a, String nomeBarbeiro) {
    final pago = a['pago'] == true;
    final id = _idDe(a);
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          if (pago)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 12),
              child: Icon(Icons.check_circle, color: Colors.greenAccent, size: 20),
            )
          else
            SizedBox(
              width: 40,
              child: Checkbox(
                value: _selecionados.contains(id),
                activeColor: _brandRed,
                visualDensity: VisualDensity.compact,
                onChanged: _processando
                    ? null
                    : (v) => setState(() {
                          if (v == true) {
                            _selecionados.add(id);
                          } else {
                            _selecionados.remove(id);
                          }
                        }),
              ),
            ),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${_fmtBrIso((a['data'] ?? '').toString())} ${a['horario'] ?? ''} • ${a['cliente_nome'] ?? ''}',
                  style: const TextStyle(color: Colors.white, fontSize: 12),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  _situacao == 'todas'
                      ? '${a['servico'] ?? ''} • ${_moeda(_num(a['valor']))} • ${_pct(_num(a['percentual']))}%'
                      : '${a['servico'] ?? ''} • ${_pct(_num(a['percentual']))}% de comissão',
                  style: TextStyle(color: _textSecondary, fontSize: 11),
                  overflow: TextOverflow.ellipsis,
                ),
                if (pago)
                  Text('PAGO em ${a['pago_em'] ?? ''}',
                      style: const TextStyle(color: Colors.greenAccent, fontSize: 10, fontWeight: FontWeight.bold)),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            _moeda(_num(a['comissao'])),
            style: TextStyle(
              color: pago ? Colors.greenAccent : Colors.orangeAccent,
              fontWeight: FontWeight.bold,
              fontSize: 12,
            ),
          ),
          if (pago)
            IconButton(
              tooltip: 'Desfazer baixa',
              visualDensity: VisualDensity.compact,
              icon: Icon(Icons.undo, color: _textSecondary, size: 18),
              onPressed: _processando ? null : () => _desfazerBaixa(a),
            )
          else
            IconButton(
              tooltip: 'Dar baixa',
              visualDensity: VisualDensity.compact,
              icon: const Icon(Icons.price_check, color: Colors.tealAccent, size: 20),
              onPressed: _processando ? null : () => _darBaixa(nomeBarbeiro, [a]),
            ),
        ],
      ),
    );
  }

  Widget _buildCardBarbeiro(Map<String, dynamic> g) {
    final todos = (g['atendimentos'] ?? []) as List<dynamic>;
    final visiveis = _filtrarAtendimentos(todos);
    final pendentesVisiveis = visiveis.where((a) => a['pago'] != true).toList();
    final pendentesTodas = todos.where((a) => a['pago'] != true).toList();
    final qtdPagas = todos.length - pendentesTodas.length;

    // Serviços calculados só com o que está visível (pendentes ou pagas, conforme o filtro)
    final Map<String, Map<String, dynamic>> porServico = {};
    for (final a in visiveis) {
      final nomeServ = (a['servico'] ?? 'Serviço').toString();
      final sv = porServico.putIfAbsent(nomeServ, () => {'qtd': 0, 'fat': 0.0, 'com': 0.0, 'pct': _num(a['percentual'])});
      sv['qtd'] = (sv['qtd'] as int) + 1;
      sv['fat'] = (sv['fat'] as double) + _num(a['valor']);
      sv['com'] = (sv['com'] as double) + _num(a['comissao']);
      sv['pct'] = _num(a['percentual']);
    }
    final selecionadosDele = todos.where((a) => a['pago'] != true && _selecionados.contains(_idDe(a))).toList();
    final totalSelecionado = selecionadosDele.fold<double>(0, (s, a) => s + _num(a['comissao']));
    final pendente = _num(g['comissao_pendente']);
    final paga = _num(g['comissao_paga']);

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: _cardColor,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white10),
      ),
      child: Column(
        children: [
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          key: PageStorageKey('comissao-${g['barbeiro_id']}'),
          tilePadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
          childrenPadding: const EdgeInsets.fromLTRB(4, 0, 12, 12),
          iconColor: _textSecondary,
          collapsedIconColor: _textSecondary,
          leading: _buildAvatarBarbeiro(_fotoDoBarbeiro(g['barbeiro_id']), radius: 18),
          title: Text(
            (g['nome'] ?? '').toString(),
            style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14),
            overflow: TextOverflow.ellipsis,
          ),
          subtitle: Text(
            _situacao == 'pendentes'
                ? '${pendentesTodas.length} atendimento(s) pendente(s)'
                : (_situacao == 'pagas'
                    ? '$qtdPagas atendimento(s) pago(s)'
                    : '${g['qtd']} corte(s) • Faturou ${_moeda(_num(g['faturamento']))}\nJá pago ${_moeda(paga)}'),
            style: TextStyle(color: _textSecondary, fontSize: 11),
          ),
          trailing: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(_situacao == 'pagas' ? 'PAGO' : (pendente > 0 ? 'PENDENTE' : 'EM DIA'),
                  style: TextStyle(color: _textSecondary, fontSize: 9, fontWeight: FontWeight.bold)),
              Text(
                _moeda(_situacao == 'pagas' ? paga : pendente),
                style: TextStyle(
                  color: (_situacao == 'pagas' || pendente <= 0) ? Colors.greenAccent : Colors.orangeAccent,
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
            ],
          ),
          children: [
            if (todos.isEmpty)
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text('Nenhum corte finalizado no período.', style: TextStyle(color: _textSecondary, fontSize: 12)),
                ),
              )
            else ...[
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: Row(
                  children: [
                    Expanded(
                      child: Text('ATENDIMENTOS', style: TextStyle(color: _textSecondary, fontSize: 10, fontWeight: FontWeight.bold)),
                    ),
                    if (pendentesVisiveis.isNotEmpty)
                      TextButton(
                        style: TextButton.styleFrom(
                          padding: const EdgeInsets.symmetric(horizontal: 8),
                          minimumSize: const Size(0, 28),
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                        onPressed: _processando
                            ? null
                            : () => setState(() {
                                  final ids = pendentesVisiveis.map<int>((a) => _idDe(a)).toList();
                                  final todosMarcados = ids.every(_selecionados.contains);
                                  if (todosMarcados) {
                                    _selecionados.removeAll(ids);
                                  } else {
                                    _selecionados.addAll(ids);
                                  }
                                }),
                        child: Text(
                          pendentesVisiveis.every((a) => _selecionados.contains(_idDe(a))) ? 'Limpar seleção' : 'Selecionar pendentes',
                          style: TextStyle(color: _brandRed, fontSize: 12, fontWeight: FontWeight.bold),
                        ),
                      ),
                  ],
                ),
              ),
              if (visiveis.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(left: 8, top: 6),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Text('Nenhum atendimento nesta situação.', style: TextStyle(color: _textSecondary, fontSize: 12)),
                  ),
                )
              else
                ...visiveis.map((a) => _linhaAtendimento(a, (g['nome'] ?? '').toString())),
              const SizedBox(height: 14),
              Padding(
                padding: const EdgeInsets.only(left: 8),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text('POR SERVIÇO', style: TextStyle(color: _textSecondary, fontSize: 10, fontWeight: FontWeight.bold)),
                ),
              ),
              ...porServico.entries.map((e) {
                final sv = e.value;
                return Padding(
                  padding: const EdgeInsets.only(top: 8, left: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(e.key,
                                style: const TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.w600)),
                            Text(
                              _situacao == 'todas'
                                  ? '${sv['qtd']}x • ${_moeda(sv['fat'] as double)} • ${_pct(sv['pct'] as double)}% de comissão'
                                  : '${sv['qtd']}x • ${_pct(sv['pct'] as double)}% de comissão',
                              style: TextStyle(color: _textSecondary, fontSize: 11),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(_moeda(sv['com'] as double),
                          style: TextStyle(
                            color: _situacao == 'pagas' ? Colors.greenAccent : Colors.orangeAccent,
                            fontWeight: FontWeight.bold,
                            fontSize: 12,
                          )),
                    ],
                  ),
                );
              }),
            ],
          ],
        ),
      ),
      if (pendentesTodas.isNotEmpty)
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
          child: Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.teal,
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(vertical: 12),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  onPressed: _processando ? null : () => _darBaixa((g['nome'] ?? '').toString(), pendentesTodas),
                  icon: const Icon(Icons.price_check, size: 18),
                  label: Text(
                    'DAR BAIXA EM TUDO • ${_moeda(pendente)}',
                    style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              ),
              if (selecionadosDele.isNotEmpty) ...[
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.teal),
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                    ),
                    onPressed: _processando ? null : () => _darBaixa((g['nome'] ?? '').toString(), selecionadosDele),
                    icon: const Icon(Icons.checklist, size: 18, color: Colors.tealAccent),
                    label: Text(
                      'SELECIONADAS (${selecionadosDele.length}) • ${_moeda(totalSelecionado)}',
                      style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 12, color: Colors.tealAccent),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final todosColab = ((_dados?['barbeiros'] ?? []) as List<dynamic>);
    final lista = todosColab.where((g) {
      if (_situacao == 'pagas') return _num(g['comissao_paga']) > 0;
      if (_situacao == 'pendentes') return _num(g['comissao_pendente']) > 0;
      return true;
    }).toList();
    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _cardColor,
        elevation: 0,
        title: Row(
          children: [
            Icon(Icons.payments_outlined, color: _brandRed, size: 20),
            const SizedBox(width: 8),
            const Text('COMISSÕES', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white70, size: 22),
            tooltip: 'Atualizar',
            onPressed: _carregar,
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _carregar,
        color: _brandRed,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(16),
          children: [
            _buildFiltros(),
            const SizedBox(height: 16),
            if (_carregando)
              Padding(
                padding: const EdgeInsets.only(top: 40),
                child: Center(child: CircularProgressIndicator(color: _brandRed)),
              )
            else if (_erro != null)
              Padding(
                padding: const EdgeInsets.only(top: 40),
                child: Center(child: Text(_erro!, style: TextStyle(color: _textSecondary, fontSize: 14), textAlign: TextAlign.center)),
              )
            else ...[
              _buildResumo(),
              const SizedBox(height: 16),
              if (lista.isEmpty)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(color: _cardColor, borderRadius: BorderRadius.circular(12)),
                  child: Text(
                    _situacao == 'pagas'
                        ? 'Nenhuma comissão paga neste período.'
                        : (_situacao == 'pendentes' ? 'Nenhuma comissão pendente neste período.' : 'Nenhum corte finalizado neste período.'),
                    style: TextStyle(color: _textSecondary, fontSize: 12),
                  ),
                )
              else
                ...lista.map((g) => _buildCardBarbeiro(Map<String, dynamic>.from(g))),
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  'Conta pelo dia do agendamento. Percentual definido na aba Comissões de cada barbeiro (padrão 40%). '
                  'Comissões pagas guardam o valor da hora da baixa.',
                  style: TextStyle(color: _textSecondary, fontSize: 10),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ==============================================================================
// AGENDAR CLIENTE (feito pelo administrador)
// ==============================================================================
class AgendarClienteScreen extends StatefulWidget {
  final DateTime? dataInicial;
  final String? barbeiroIdInicial;

  const AgendarClienteScreen({super.key, this.dataInicial, this.barbeiroIdInicial});

  @override
  State<AgendarClienteScreen> createState() => _AgendarClienteScreenState();
}

class _AgendarClienteScreenState extends State<AgendarClienteScreen> {
  final Color _bgColor = const Color(0xFF121212);
  final Color _cardColor = const Color(0xFF1E1E1E);
  final Color _brandRed = const Color(0xFFCF243E);
  final Color _textSecondary = const Color(0xFF9E9E9E);

  static const Map<String, String> _formasPagamento = {
    'presencial': 'Pagar no local',
    'pix': 'Pix',
    'cartao': 'Cartão',
    'debito': 'Débito',
    'credito': 'Crédito',
    'dinheiro': 'Dinheiro',
    'plano': 'Plano (assinante)',
  };

  List<dynamic> _clientes = [];
  List<dynamic> _barbeiros = [];
  List<dynamic> _servicos = [];
  List<String> _horarios = [];

  Map<String, dynamic>? _cliente;
  String? _barbeiroId;
  late DateTime _data;
  String? _horario;
  String? _servico;
  String _pagamento = 'presencial';
  final TextEditingController _telefoneCtrl = TextEditingController();

  bool _carregando = true;
  bool _carregandoHorarios = false;
  bool _salvando = false;

  @override
  void initState() {
    super.initState();
    final base = widget.dataInicial ?? DateTime.now();
    final hoje = DateTime.now();
    final hojeSemHora = DateTime(hoje.year, hoje.month, hoje.day);
    final baseSemHora = DateTime(base.year, base.month, base.day);
    _data = baseSemHora.isBefore(hojeSemHora) ? hojeSemHora : baseSemHora;
    _barbeiroId = widget.barbeiroIdInicial;
    _carregarDados();
  }

  @override
  void dispose() {
    _telefoneCtrl.dispose();
    super.dispose();
  }

  String _fmtApi(DateTime d) =>
      '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  String _fmtBr(DateTime d) =>
      '${d.day.toString().padLeft(2, '0')}/${d.month.toString().padLeft(2, '0')}/${d.year}';

  void _snack(String msg, {bool erro = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), backgroundColor: erro ? Colors.red : Colors.teal),
    );
  }

  Future<void> _carregarDados() async {
    try {
      final respostas = await Future.wait([
        http.get(Uri.parse('${AppConfig.apiUrl}/admin/usuarios'), headers: AppConfig.adminHeaders),
        http.get(Uri.parse('${AppConfig.apiUrl}/admin/barbeiros'), headers: AppConfig.adminHeaders),
        http.get(Uri.parse('${AppConfig.apiUrl}/admin/servicos'), headers: AppConfig.adminHeaders),
      ]);
      if (!mounted) return;
      final ru = respostas[0], rb = respostas[1], rs = respostas[2];
      setState(() {
        if (ru.statusCode == 200) _clientes = jsonDecode(ru.body)['usuarios'] ?? [];
        if (rb.statusCode == 200) {
          final todos = jsonDecode(rb.body)['barbeiros'] ?? [];
          _barbeiros = todos.where((b) => !(b['ativo'] == 0 || b['ativo'] == false)).toList();
        }
        if (rs.statusCode == 200) _servicos = jsonDecode(rs.body)['servicos'] ?? [];
        if (_barbeiroId != null && !_barbeiros.any((b) => b['id'].toString() == _barbeiroId)) {
          _barbeiroId = null;
        }
        _carregando = false;
      });
      if (_barbeiroId != null) {
        _carregarHorarios();
        _carregarServicosDoBarbeiro();
      }
    } catch (e) {
      debugPrint('Erro ao carregar dados do agendamento: $e');
      if (mounted) setState(() => _carregando = false);
      _snack('Erro de conexão com o servidor.', erro: true);
    }
  }

  // Só lista os serviços que o profissional realiza (aba Comissões do barbeiro > "Realiza")
  Future<void> _carregarServicosDoBarbeiro() async {
    if (_barbeiroId == null) return;
    try {
      final resp = await http.get(Uri.parse('${AppConfig.apiUrl}/servicos?barbeiro_id=$_barbeiroId'));
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final lista = jsonDecode(resp.body)['servicos'] ?? [];
        setState(() {
          _servicos = lista;
          if (_servico != null && !_servicos.any((s) => (s['nome'] ?? '').toString() == _servico)) {
            _servico = null;
          }
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar serviços do profissional: $e');
    }
  }

  Future<void> _carregarHorarios() async {
    if (_barbeiroId == null) return;
    setState(() {
      _carregandoHorarios = true;
      _horario = null;
    });
    try {
      final resp = await http.get(
        Uri.parse('${AppConfig.apiUrl}/horarios-disponiveis?barbeiro_id=$_barbeiroId&data=${_fmtApi(_data)}'),
      );
      if (!mounted) return;
      if (resp.statusCode == 200) {
        final lista = jsonDecode(resp.body) as List<dynamic>;
        setState(() {
          _horarios = lista.map((h) => h.toString()).toList();
          _carregandoHorarios = false;
        });
      } else {
        setState(() {
          _horarios = [];
          _carregandoHorarios = false;
        });
      }
    } catch (e) {
      debugPrint('Erro ao carregar horários: $e');
      if (mounted) {
        setState(() {
          _horarios = [];
          _carregandoHorarios = false;
        });
      }
    }
  }

  Future<void> _escolherData() async {
    final hoje = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: _data,
      firstDate: DateTime(hoje.year, hoje.month, hoje.day),
      lastDate: DateTime(2030),
      builder: (context, child) {
        return Theme(
          data: ThemeData.dark().copyWith(
            colorScheme: ColorScheme.dark(primary: _brandRed, onSurface: Colors.white),
          ),
          child: child!,
        );
      },
    );
    if (picked != null) {
      setState(() => _data = picked);
      _carregarHorarios();
    }
  }

  Future<void> _escolherCliente() async {
    final escolhido = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: _cardColor,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => _SeletorClienteSheet(clientes: _clientes),
    );
    if (escolhido != null) setState(() => _cliente = escolhido);
  }

  Future<void> _salvar() async {
    if (_cliente == null) return _snack('Escolha o cliente.', erro: true);
    if (_barbeiroId == null) return _snack('Escolha o profissional.', erro: true);
    if (_servico == null) return _snack('Escolha o serviço.', erro: true);
    if (_horario == null) return _snack('Escolha o horário.', erro: true);

    setState(() => _salvando = true);
    try {
      final resp = await http.post(
        Uri.parse('${AppConfig.apiUrl}/admin/agendamentos'),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'cliente_id': _cliente!['id'],
          'barbeiro_id': int.tryParse(_barbeiroId!) ?? 0,
          'data': _fmtApi(_data),
          'horario': _horario,
          'servico': _servico,
          'tipo_pagamento': _pagamento,
          'cliente_telefone': _telefoneCtrl.text.trim(),
        }),
      );
      if (!mounted) return;
      if (resp.statusCode == 201) {
        _snack('✅ Cliente agendado com sucesso!');
        Navigator.pop(context, true);
        return;
      }
      String msg = 'Não foi possível agendar.';
      try {
        msg = (jsonDecode(resp.body)['mensagem'] ?? msg).toString();
      } catch (_) {}
      _snack(msg, erro: true);
      if (resp.statusCode == 409) _carregarHorarios();
    } catch (e) {
      debugPrint('Erro ao agendar cliente: $e');
      _snack('Erro de conexão com o servidor.', erro: true);
    } finally {
      if (mounted) setState(() => _salvando = false);
    }
  }

  InputDecoration _decoracao(String label, IconData icone) {
    return InputDecoration(
      labelText: label,
      labelStyle: TextStyle(color: _textSecondary),
      prefixIcon: Icon(icone, color: _brandRed),
      filled: true,
      fillColor: _cardColor,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
    );
  }

  Widget _campoToque({required IconData icone, required String rotulo, required String valor, required VoidCallback onTap}) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        decoration: BoxDecoration(color: _cardColor, borderRadius: BorderRadius.circular(12)),
        child: Row(
          children: [
            Icon(icone, color: _brandRed, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(rotulo, style: TextStyle(color: _textSecondary, fontSize: 11)),
                  const SizedBox(height: 2),
                  Text(valor, style: const TextStyle(color: Colors.white, fontSize: 15), overflow: TextOverflow.ellipsis),
                ],
              ),
            ),
            Icon(Icons.chevron_right, color: _textSecondary),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _cardColor,
        elevation: 0,
        title: const Text('AGENDAR CLIENTE', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
      ),
      body: _carregando
          ? Center(child: CircularProgressIndicator(color: _brandRed))
          : ListView(
              padding: const EdgeInsets.all(16),
              children: [
                _campoToque(
                  icone: Icons.person_search,
                  rotulo: 'Cliente',
                  valor: _cliente == null ? 'Toque para escolher' : (_cliente!['nome'] ?? '').toString(),
                  onTap: _escolherCliente,
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _barbeiroId,
                  isExpanded: true,
                  dropdownColor: _cardColor,
                  style: const TextStyle(color: Colors.white, fontSize: 15),
                  decoration: _decoracao('Profissional', Icons.content_cut),
                  items: _barbeiros
                      .map<DropdownMenuItem<String>>((b) => DropdownMenuItem<String>(
                            value: b['id'].toString(),
                            child: Text((b['nome'] ?? '').toString(), overflow: TextOverflow.ellipsis),
                          ))
                      .toList(),
                  onChanged: (v) {
                    setState(() => _barbeiroId = v);
                    _carregarHorarios();
                    _carregarServicosDoBarbeiro();
                  },
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  value: _servico,
                  isExpanded: true,
                  dropdownColor: _cardColor,
                  style: const TextStyle(color: Colors.white, fontSize: 15),
                  decoration: _decoracao('Serviço', Icons.sell_outlined),
                  items: _servicos
                      .map<DropdownMenuItem<String>>((s) => DropdownMenuItem<String>(
                            value: (s['nome'] ?? '').toString(),
                            child: Text(
                              '${s['nome']} • R\$ ${(double.tryParse('${s['preco']}') ?? 0).toStringAsFixed(2).replaceAll('.', ',')}',
                              overflow: TextOverflow.ellipsis,
                            ),
                          ))
                      .toList(),
                  onChanged: (v) => setState(() => _servico = v),
                ),
                const SizedBox(height: 12),
                _campoToque(
                  icone: Icons.calendar_month,
                  rotulo: 'Data',
                  valor: _fmtBr(_data),
                  onTap: _escolherData,
                ),
                const SizedBox(height: 12),
                Text('HORÁRIO', style: TextStyle(color: _textSecondary, fontSize: 11, fontWeight: FontWeight.bold)),
                const SizedBox(height: 8),
                if (_barbeiroId == null)
                  Text('Escolha o profissional para ver os horários livres.', style: TextStyle(color: _textSecondary, fontSize: 12))
                else if (_carregandoHorarios)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Center(child: CircularProgressIndicator(color: _brandRed)),
                  )
                else if (_horarios.isEmpty)
                  Text('Nenhum horário livre nesta data.', style: TextStyle(color: _textSecondary, fontSize: 12))
                else
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: _horarios.map((h) {
                      final ativo = _horario == h;
                      return ChoiceChip(
                        label: Text(h, style: TextStyle(color: ativo ? Colors.white : Colors.white70, fontSize: 13)),
                        selected: ativo,
                        selectedColor: _brandRed,
                        backgroundColor: _cardColor,
                        showCheckmark: false,
                        onSelected: (_) => setState(() => _horario = h),
                      );
                    }).toList(),
                  ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String>(
                  value: _pagamento,
                  isExpanded: true,
                  dropdownColor: _cardColor,
                  style: const TextStyle(color: Colors.white, fontSize: 15),
                  decoration: _decoracao('Forma de pagamento', Icons.payments_outlined),
                  items: _formasPagamento.entries
                      .map((e) => DropdownMenuItem<String>(value: e.key, child: Text(e.value)))
                      .toList(),
                  onChanged: (v) => setState(() => _pagamento = v ?? 'presencial'),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _telefoneCtrl,
                  keyboardType: TextInputType.phone,
                  maxLength: 20,
                  style: const TextStyle(color: Colors.white),
                  decoration: _decoracao('Telefone (opcional)', Icons.phone_outlined).copyWith(counterText: ''),
                ),
                const SizedBox(height: 20),
                SizedBox(
                  height: 50,
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _brandRed,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    ),
                    onPressed: _salvando ? null : _salvar,
                    icon: _salvando
                        ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Icon(Icons.check),
                    label: Text(_salvando ? 'Agendando...' : 'CONFIRMAR AGENDAMENTO',
                        style: const TextStyle(fontWeight: FontWeight.bold)),
                  ),
                ),
                const SizedBox(height: 24),
              ],
            ),
    );
  }
}

class _SeletorClienteSheet extends StatefulWidget {
  final List<dynamic> clientes;
  const _SeletorClienteSheet({required this.clientes});

  @override
  State<_SeletorClienteSheet> createState() => _SeletorClienteSheetState();
}

class _SeletorClienteSheetState extends State<_SeletorClienteSheet> {
  String _busca = '';

  @override
  Widget build(BuildContext context) {
    final termo = _busca.trim().toLowerCase();
    final filtrados = widget.clientes.where((c) {
      if (termo.isEmpty) return true;
      return (c['nome'] ?? '').toString().toLowerCase().contains(termo) ||
          (c['email'] ?? '').toString().toLowerCase().contains(termo);
    }).toList();

    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.75,
        child: Column(
          children: [
            const SizedBox(height: 12),
            const Text('Escolher cliente', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
            Padding(
              padding: const EdgeInsets.all(12),
              child: TextField(
                autofocus: false,
                style: const TextStyle(color: Colors.white),
                decoration: InputDecoration(
                  hintText: 'Buscar por nome ou e-mail',
                  hintStyle: const TextStyle(color: Color(0xFF9E9E9E)),
                  prefixIcon: const Icon(Icons.search, color: Color(0xFF9E9E9E)),
                  filled: true,
                  fillColor: const Color(0xFF121212),
                  border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                ),
                onChanged: (v) => setState(() => _busca = v),
              ),
            ),
            Expanded(
              child: filtrados.isEmpty
                  ? const Center(child: Text('Nenhum cliente encontrado.', style: TextStyle(color: Color(0xFF9E9E9E))))
                  : ListView.builder(
                      itemCount: filtrados.length,
                      itemBuilder: (context, i) {
                        final c = filtrados[i];
                        return ListTile(
                          leading: const CircleAvatar(
                            backgroundColor: Color(0xFF121212),
                            child: Icon(Icons.person, color: Color(0xFFCF243E)),
                          ),
                          title: Text((c['nome'] ?? '').toString(), style: const TextStyle(color: Colors.white)),
                          subtitle: Text((c['email'] ?? '').toString(),
                              style: const TextStyle(color: Color(0xFF9E9E9E), fontSize: 12)),
                          onTap: () => Navigator.pop(context, Map<String, dynamic>.from(c)),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}