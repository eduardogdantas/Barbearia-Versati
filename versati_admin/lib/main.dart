import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

// ==============================================================================
// CONFIGURAÇÃO CENTRAL DA API E SEGURANÇA
// ==============================================================================
class AppConfig {
  static const String baseUrl = 'http://localhost:5000';
  static const String apiUrl = '$baseUrl/api';
  static const String adminToken = 'token_secreto_para_proteger_o_flutter'; 

  // Helper centralizado para injetar o token de segurança nas requisições admin
  static Map<String, String> get adminHeaders => {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $adminToken',
      };
}

void main() {
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
  bool _modoLogin = true;
  bool _obscureText = true;
  bool _isLoading = false;

  final _nomeController = TextEditingController();
  final _emailController = TextEditingController();
  final _senhaController = TextEditingController();

  final Color _bgBlack = const Color(0xFF000000);
  final Color _cardDark = const Color(0xFF121212);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF8E8E93);

  final String _baseUrl = AppConfig.apiUrl;

  Future<void> _submeterFormulario() async {
    final email = _emailController.text.trim();
    final senha = _senhaController.text.trim();
    final nome = _nomeController.text.trim();

    if (email.isEmpty || senha.isEmpty || (!_modoLogin && nome.isEmpty)) {
      _mostrarMensagem('Preencha todos os campos!');
      return;
    }

    setState(() => _isLoading = true);

    final String endpoint = _modoLogin ? '$_baseUrl/login' : '$_baseUrl/cadastro';
    final Map<String, dynamic> payload = _modoLogin
        ? {'email': email, 'senha': senha}
        : {'nome': nome, 'email': email, 'senha': senha};

    try {
      final response = await http.post(
        Uri.parse(endpoint),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(payload),
      );

      final resData = jsonDecode(response.body);
      if (!mounted) return;
      setState(() => _isLoading = false);

      if ((response.statusCode == 200 || response.statusCode == 201) && resData['sucesso'] == true) {
        _mostrarMensagem(resData['mensagem']);
        
        if (!_modoLogin) {
          setState(() {
            _modoLogin = true;
            _senhaController.clear();
          });
        } else {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(
              builder: (context) => const MainMultiTaskScreen(),
            ),
          );
        }
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
    _nomeController.dispose();
    _emailController.dispose();
    _senhaController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
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
                  'logo_versati.jpeg',
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
                    _modoLogin
                        ? 'Painel Administrativo - Faça seu login'
                        : 'Preencha os dados para cadastrar um administrador',
                    style: TextStyle(
                      color: _textSecondary,
                      fontSize: 14,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
                const SizedBox(height: 20),

                if (!_modoLogin) ...[
                  TextField(
                    controller: _nomeController,
                    style: const TextStyle(color: Colors.white),
                    decoration: _inputDecoration('Nome Completo', Icons.person_outline),
                  ),
                  const SizedBox(height: 16),
                ],

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

                if (_modoLogin)
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: () {},
                      child: Text(
                        'Esqueceu a senha?',
                        style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),

                const SizedBox(height: 12),

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
                            _modoLogin ? 'ENTRAR NO PAINEL' : 'CADASTRAR ADMIN',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.bold,
                              color: Colors.white,
                              letterSpacing: 1.2,
                            ),
                          ),
                  ),
                ),
                const SizedBox(height: 24),

                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      _modoLogin ? 'Não tem acesso admin? ' : 'Já possui acesso? ',
                      style: TextStyle(color: _textSecondary),
                    ),
                    GestureDetector(
                      onTap: () {
                        setState(() {
                          _modoLogin = !_modoLogin;
                        });
                      },
                      child: Text(
                        _modoLogin ? 'Cadastre-se aqui.' : 'Faça login aqui.',
                        style: TextStyle(
                          color: _brandRed,
                          fontWeight: FontWeight.bold,
                          decoration: TextDecoration.underline,
                        ),
                      ),
                    ),
                  ],
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
          if (_currentIndex == 1)
            IconButton(
              icon: const Icon(Icons.refresh, color: Colors.white),
              tooltip: 'Atualizar Dados',
              onPressed: () {
                _financeiroKey.currentState?._carregarDados(manual: true);
              },
            ),
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

  // Utilizando a configuração central da API
  final String _apiUrl = '${AppConfig.apiUrl}/admin/dados';

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
        headers: AppConfig.adminHeaders, // Corrigido para usar os headers padronizados com o token correto
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

  // Restante dos métodos da classe continuam iguais...
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
  List<dynamic> _servicosMaisSolicitados = [];
  double _receitaAssinaturasAtivas = 0;
  double _receitaAssinaturasHoje = 0;
  double _valorTotalFinalizados = 0;
  bool _isLoading = true;
  Timer? _timerTempoReal;

  final String _apiUrl = '${AppConfig.apiUrl}/admin/dados';

  @override
  void initState() {
    super.initState();
    _carregarDados(manual: true);

    _timerTempoReal = Timer.periodic(const Duration(seconds: 5), (_) {
      _carregarDados(manual: false);
    });
  }

  @override
  void dispose() {
    _timerTempoReal?.cancel();
    super.dispose();
  }

  Future<void> _carregarDados({bool manual = false}) async {
    if (manual && mounted) {
      setState(() => _isLoading = true);
    }

    try {
      final response = await http.get(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (mounted) {
          setState(() {
            _dashboardData = data['dashboard'] ?? {};
            _finalizados = data['finalizados'] ?? [];
            _servicosMaisSolicitados = data['servicos_mais_solicitados'] ?? [];
            _receitaAssinaturasAtivas = double.tryParse('${data['receita_assinaturas_ativas'] ?? 0}') ?? 0;
            _receitaAssinaturasHoje = double.tryParse('${data['receita_assinaturas_hoje'] ?? 0}') ?? 0;
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

  @override
  Widget build(BuildContext context) {
    return _isLoading
        ? Center(child: CircularProgressIndicator(color: _brandRed))
        : RefreshIndicator(
            onRefresh: () => _carregarDados(manual: true),
            color: _brandRed,
            child: SingleChildScrollView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.all(16.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
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
                            Expanded(
                              child: Text(
                                'VALOR TOTAL EM CORTES FINALIZADOS',
                                style: TextStyle(color: _textSecondary, fontSize: 11, fontWeight: FontWeight.bold),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'R\$ ${_valorTotalFinalizados.toStringAsFixed(2).replaceAll('.', ',')}',
                          style: const TextStyle(color: Colors.white, fontSize: 30, fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Soma de todos os atendimentos marcados como concluídos.',
                          style: TextStyle(color: _textSecondary, fontSize: 10),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      color: _cardDark,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('RECEITA DE ASSINATURAS ATIVAS', style: TextStyle(color: _textSecondary, fontSize: 11, fontWeight: FontWeight.bold)),
                        const SizedBox(height: 8),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'R\$ ${_receitaAssinaturasAtivas.toStringAsFixed(2).replaceAll('.', ',')}',
                              style: const TextStyle(color: Colors.white, fontSize: 26, fontWeight: FontWeight.bold),
                            ),
                            if (_receitaAssinaturasHoje > 0)
                              Container(
                                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                decoration: BoxDecoration(
                                  color: Colors.green.withOpacity(0.2),
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  '+R\$ ${_receitaAssinaturasHoje.toStringAsFixed(2).replaceAll('.', ',')} hoje',
                                  style: const TextStyle(color: Colors.greenAccent, fontSize: 12, fontWeight: FontWeight.bold),
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),

                  Row(
                    children: [
                      _buildMetricCard('HOJE', '${_dashboardData['diario'] ?? 0} Cortes', Icons.today),
                      const SizedBox(width: 8),
                      _buildMetricCard('SEMANA', '${_dashboardData['semanal'] ?? 0} Cortes', Icons.calendar_view_week),
                      const SizedBox(width: 8),
                      _buildMetricCard('MÊS', '${_dashboardData['mensal'] ?? 0} Cortes', Icons.calendar_month),
                    ],
                  ),
                  const SizedBox(height: 24),

                  const Text('Serviços Mais Solicitados', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: _cardDark,
                      borderRadius: BorderRadius.circular(16),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: _servicosMaisSolicitados.isEmpty
                        ? Padding(
                            padding: const EdgeInsets.symmetric(vertical: 8),
                            child: Text('Nenhum agendamento registrado ainda.', style: TextStyle(color: _textSecondary, fontSize: 12)),
                          )
                        : Column(
                            children: _servicosMaisSolicitados.map((c) => _buildCorteMaisVendidoRow(c)).toList(),
                          ),
                  ),
                  const SizedBox(height: 24),

                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: const Text(
                          'Cortes Finalizados',
                          style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text(
                        '${_finalizados.length} concluídos',
                        style: const TextStyle(color: Colors.greenAccent, fontSize: 12),
                      ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  if (_finalizados.isEmpty)
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
                      itemCount: _finalizados.length,
                      itemBuilder: (context, index) {
                        final item = _finalizados[index];
                        return _buildFinalizadoTile(item);
                      },
                    ),
                ],
              ),
            ),
          );
  }

  Widget _buildMetricCard(String title, String value, IconData icon) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
        decoration: BoxDecoration(
          color: _cardDark,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: Column(
          children: [
            Icon(icon, color: _brandRed, size: 20),
            const SizedBox(height: 6),
            Text(
              value,
              style: const TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 2),
            Text(
              title,
              style: TextStyle(color: _textSecondary, fontSize: 10, fontWeight: FontWeight.w600),
            ),
          ],
        ),
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
              Expanded(
                child: Text(
                  c['nome'] ?? '',
                  style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              Text(
                '${c['quantidade']}x (${(porcentagem * 100).toStringAsFixed(0)}%)',
                style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 12),
              ),
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
          onTap: () {
            Navigator.pushReplacement(
              context,
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
                  hintText: 'Mínimo 6 caracteres',
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
          const SizedBox(height: 8),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Row(
                children: [
                  Icon(Icons.lock_outline, size: 16, color: _brandRed),
                  const SizedBox(width: 8),
                  Text(
                    'Gerenciar Senha do Usuário',
                    style: TextStyle(color: _textSecondary, fontSize: 13),
                  ),
                ],
              ),
              InkWell(
                onTap: () => _exibirDialogoResetarSenha(
                  id,
                  u['nome'] ?? 'Cliente',
                ),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.orange.withOpacity(0.2),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: Colors.orange, width: 0.8),
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.edit, color: Colors.orangeAccent, size: 12),
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
    XFile? imagemXFile;

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
                imagemXFile = pickedFile;
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
// GERENCIAR ASSINATURAS
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
  List<dynamic> _planosFiltrados = [];
  bool _isLoading = true;
  String? _dataFiltro;

  @override
  void initState() {
    super.initState();
    _carregarPlanos();
  }

  Future<void> _carregarPlanos() async {
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
          _planos = data['planos'] ?? [];
          _aplicarFiltroData();
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

  void _aplicarFiltroData() {
    if (_dataFiltro == null || _dataFiltro!.isEmpty) {
      _planosFiltrados = List.from(_planos);
    } else {
      _planosFiltrados = _planos.where((p) {
        String validade = (p['validade'] ?? '').toString();
        String criadoEm = (p['criado_em'] ?? '').toString(); 
        return validade.contains(_dataFiltro!) || criadoEm.contains(_dataFiltro!);
      }).toList();
    }
  }

  Future<void> _selecionarDataFiltro() async {
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
        _aplicarFiltroData();
      });
    }
  }

  void _limparFiltro() {
    setState(() {
      _dataFiltro = null;
      _planosFiltrados = List.from(_planos);
    });
  }

  Future<void> _cancelarAssinaturaAPI(int assinaturaId) async {
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
          const SnackBar(content: Text('🚫 Assinatura cancelada com sucesso!'), backgroundColor: Colors.orange),
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

  @override
  Widget build(BuildContext context) {
    int ativos = _planosFiltrados.where((p) => (p['status'] ?? '').toString().toLowerCase() == 'ativo').length;
    int vencidos = _planosFiltrados.where((p) => (p['status'] ?? '').toString().toLowerCase() == 'vencido').length;
    int cancelados = _planosFiltrados.where((p) {
      String st = (p['status'] ?? '').toString().toLowerCase();
      return st == 'inativo' || st == 'cancelado';
    }).length;
    
    double totalValor = _planosFiltrados.fold(0.0, (sum, p) {
      if ((p['status'] ?? '').toString().toLowerCase() == 'ativo') {
        return sum + (double.tryParse('${p['preco']}') ?? 0.0);
      }
      return sum;
    });

    return Scaffold(
      backgroundColor: const Color(0xFF000000),
      appBar: AppBar(
        backgroundColor: _cardDark,
        elevation: 0,
        title: const Text('STATUS DE ASSINATURAS', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, color: Colors.white), onPressed: _carregarPlanos),
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
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(
                      color: _cardDark,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white10),
                    ),
                    child: Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Resumo Geral', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 14)),
                            Row(
                              children: [
                                if (_dataFiltro != null)
                                  IconButton(
                                    icon: const Icon(Icons.clear, color: Colors.redAccent, size: 18),
                                    onPressed: _limparFiltro,
                                    tooltip: 'Limpar Filtro',
                                  ),
                                InkWell(
                                  onTap: _selecionarDataFiltro,
                                  child: Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                                    decoration: BoxDecoration(
                                      color: _brandRed.withOpacity(0.2),
                                      borderRadius: BorderRadius.circular(8),
                                      border: Border.all(color: _brandRed),
                                    ),
                                    child: Row(
                                      children: [
                                        const Icon(Icons.calendar_today, color: Colors.white, size: 12),
                                        const SizedBox(width: 4),
                                        Text(_dataFiltro ?? 'Filtrar Data', style: const TextStyle(color: Colors.white, fontSize: 11)),
                                      ],
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Row(
                          children: [
                            _buildDashCard('Ativos', '$ativos', Colors.greenAccent),
                            const SizedBox(width: 8),
                            _buildDashCard('Vencidos', '$vencidos', Colors.orangeAccent),
                            const SizedBox(width: 8),
                            _buildDashCard('Cancelados', '$cancelados', _brandRed),
                          ],
                        ),
                        const SizedBox(height: 8),
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
                              const Text('Total Planos Ativos:', style: TextStyle(color: Colors.grey, fontSize: 12)),
                              Text('R\$ ${totalValor.toStringAsFixed(2).replaceAll('.', ',')}', style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  const Text('Lista de Assinaturas', style: TextStyle(color: Colors.white70, fontSize: 13, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 10),
                  _planosFiltrados.isEmpty
                      ? Padding(
                          padding: const EdgeInsets.only(top: 40),
                          child: Center(
                            child: Text('Nenhuma assinatura encontrada para este filtro.', style: TextStyle(color: _textSecondary)),
                          ),
                        )
                      : ListView.builder(
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          itemCount: _planosFiltrados.length,
                          itemBuilder: (context, index) {
                            final p = _planosFiltrados[index];
                            
                            String statusBanco = (p['status'] ?? 'ativo').toString().toLowerCase();
                            bool isAtivo = statusBanco == 'ativo' || statusBanco == 'active';
                            
                            Color corStatus = isAtivo ? Colors.greenAccent : _brandRed;
                            Color corBorda = isAtivo ? Colors.green.withOpacity(0.25) : _brandRed.withOpacity(0.4);
                            String textoStatus = isAtivo ? 'ATIVO' : 'CANCELADO / INATIVO';
                            IconData iconeStatus = isAtivo ? Icons.check_circle : Icons.block;

                            return Container(
                              margin: const EdgeInsets.only(bottom: 12),
                              padding: const EdgeInsets.all(16),
                              decoration: BoxDecoration(
                                color: _cardDark,
                                borderRadius: BorderRadius.circular(12),
                                border: Border.all(color: corBorda),
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
                                            Text(
                                              p['cliente_nome'] ?? 'Cliente',
                                              style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                                            ),
                                            const SizedBox(height: 2),
                                            Text(
                                              p['cliente_email'] ?? '',
                                              style: TextStyle(color: _textSecondary, fontSize: 12),
                                            ),
                                          ],
                                        ),
                                      ),
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                                        decoration: BoxDecoration(
                                          color: corStatus.withOpacity(0.15),
                                          borderRadius: BorderRadius.circular(8),
                                        ),
                                        child: Row(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                            Icon(iconeStatus, color: corStatus, size: 14),
                                            const SizedBox(width: 4),
                                            Text(textoStatus, style: TextStyle(color: corStatus, fontSize: 10, fontWeight: FontWeight.bold)),
                                          ],
                                        ),
                                      ),
                                    ],
                                  ),
                                  const Divider(color: Colors.white10, height: 20),
                                  Row(
                                    children: [
                                      Icon(Icons.card_membership, color: _brandRed, size: 18),
                                      const SizedBox(width: 8),
                                      Text(
                                        p['nome'] ?? 'Plano',
                                        style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13),
                                      ),
                                      const Spacer(),
                                      Text(
                                        'R\$ ${(double.tryParse('${p['preco']}') ?? 0).toStringAsFixed(2).replaceAll('.', ',')}',
                                        style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 14),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),
                                  Row(
                                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                    children: [
                                      Text(
                                        isAtivo ? 'Ativo até ${p['validade'] ?? '--/--/----'}' : 'Assinatura cancelada',
                                        style: TextStyle(color: isAtivo ? _textSecondary : _brandRed, fontSize: 12),
                                      ),
                                      if (isAtivo)
                                        InkWell(
                                          onTap: () => _cancelarAssinaturaAPI(p['id']),
                                          child: Container(
                                            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                            decoration: BoxDecoration(
                                              color: _brandRed.withOpacity(0.15),
                                              borderRadius: BorderRadius.circular(6),
                                              border: Border.all(color: _brandRed, width: 0.8),
                                            ),
                                            child: const Text(
                                              'CANCELAR',
                                              style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.bold),
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
                ],
              ),
            ),
    );
  }

  Widget _buildDashCard(String titulo, String valor, Color cor) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
        decoration: BoxDecoration(
          color: Colors.black,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white12),
        ),
        child: Column(
          children: [
            Text(titulo, style: const TextStyle(color: Colors.grey, fontSize: 11)),
            const SizedBox(height: 4),
            Text(valor, style: TextStyle(color: cor, fontWeight: FontWeight.bold, fontSize: 16)),
          ],
        ),
      ),
    );
  }
}

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
    XFile? imagemXFile;

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
                imagemXFile = pickedFile;
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
// GERENCIAR PLANOS DE ASSINATURA (CATÁLOGO EXIBIDO NO SITE)
// ==============================================================================

class GerenciarPlanosScreen extends StatefulWidget {
  const GerenciarPlanosScreen({super.key});

  @override
  State<GerenciarPlanosScreen> createState() => _GerenciarPlanosScreenState();
}

class _GerenciarPlanosScreenState extends State<GerenciarPlanosScreen> {
  final Color _bgDark = const Color(0xFF0A0A0A);
  final Color _cardDark = const Color(0xFF161618);
  final Color _brandRed = const Color(0xFFE5243B);
  final Color _textSecondary = const Color(0xFF9CA3AF);

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
      if ((response.statusCode == 200 || response.statusCode == 201) && resData['sucesso'] == true) {
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
      final resData = jsonDecode(response.body);
      if (!mounted) return;
      if (response.statusCode == 200 && (resData['sucesso'] == true || resData['sucesso'] == null)) {
        _mostrarSnack('✅ Plano atualizado com sucesso!');
        _carregarPlanos();
      } else {
        _mostrarSnack('❌ ${resData['mensagem'] ?? 'Erro ao atualizar plano.'}');
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

  Future<void> _confirmarRemocao(int id) async {
    final confirmar = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardDark,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('EXCLUIR PLANO', style: TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold)),
        content: const Text('Tem certeza de que deseja remover este plano permanentemente?', style: TextStyle(color: Colors.grey)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancelar', style: TextStyle(color: Colors.grey)),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Excluir', style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );

    if (confirmar == true) {
      _removerPlanoAPI(id);
    }
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
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
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
              const SizedBox(height: 12),
              TextField(
                controller: descricaoCtrl,
                maxLines: 2,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(labelText: 'Descrição (aparece no site)', labelStyle: TextStyle(color: Colors.grey)),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: precoCtrl,
                keyboardType: TextInputType.number,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(labelText: 'Preço mensal (Ex: 99.90)', labelStyle: TextStyle(color: Colors.grey)),
              ),
              const SizedBox(height: 12),
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
            style: ElevatedButton.styleFrom(backgroundColor: _brandRed, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
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
      backgroundColor: _bgDark,
      appBar: AppBar(
        backgroundColor: _bgDark,
        elevation: 0,
        centerTitle: true,
        title: const Text('PLANOS DE ASSINATURA', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold, letterSpacing: 1.1)),
        iconTheme: const IconThemeData(color: Colors.white),
        actions: [
          IconButton(icon: const Icon(Icons.refresh, size: 22), onPressed: _carregarPlanos),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        backgroundColor: _brandRed,
        elevation: 4,
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
                    padding: const EdgeInsets.all(16),
                    itemCount: _planos.length,
                    itemBuilder: (context, index) {
                      final p = _planos[index];
                      final double preco = double.tryParse(p['preco'].toString()) ?? 0;
                      final bool ativo = (p['ativo'] ?? 1).toString() == '1' || p['ativo'] == true;

                      return Container(
                        margin: const EdgeInsets.only(bottom: 16),
                        padding: const EdgeInsets.all(18),
                        decoration: BoxDecoration(
                          color: _cardDark,
                          borderRadius: BorderRadius.circular(16),
                          border: Border.all(
                            color: ativo ? Colors.white.withOpacity(0.06) : _brandRed.withOpacity(0.3),
                            width: 1,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.black.withOpacity(0.3),
                              blurRadius: 8,
                              offset: const Offset(0, 4),
                            ),
                          ],
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
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
                                  style: TextStyle(color: _brandRed, fontWeight: FontWeight.bold, fontSize: 15),
                                ),
                              ],
                            ),
                            if ((p['descricao'] ?? '').toString().isNotEmpty) ...[
                              const SizedBox(height: 8),
                              Text(
                                p['descricao'],
                                style: TextStyle(color: _textSecondary, fontSize: 13, height: 1.3),
                              ),
                            ],
                            const Padding(
                              padding: EdgeInsets.symmetric(vertical: 12),
                              child: Divider(color: Colors.white10, height: 1),
                            ),
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                if (!ativo)
                                  Container(
                                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                    decoration: BoxDecoration(
                                      color: Colors.red.withOpacity(0.1),
                                      borderRadius: BorderRadius.circular(6),
                                    ),
                                    child: const Text('OCULTO NO SITE', style: TextStyle(color: Colors.redAccent, fontSize: 9, fontWeight: FontWeight.bold)),
                                  )
                                else
                                  const SizedBox.shrink(),
                                Row(
                                  children: [
                                    InkWell(
                                      onTap: () => _abrirDialogoPlano(planoExistente: p),
                                      borderRadius: BorderRadius.circular(8),
                                      child: Container(
                                        padding: const EdgeInsets.all(8),
                                        decoration: BoxDecoration(
                                          color: Colors.white.withOpacity(0.05),
                                          borderRadius: BorderRadius.circular(8),
                                        ),
                                        child: const Icon(Icons.edit_outlined, color: Colors.orangeAccent, size: 18),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    InkWell(
                                      onTap: () => _confirmarRemocao(p['id']),
                                      borderRadius: BorderRadius.circular(8),
                                      child: Container(
                                        padding: const EdgeInsets.all(8),
                                        decoration: BoxDecoration(
                                          color: Colors.white.withOpacity(0.05),
                                          borderRadius: BorderRadius.circular(8),
                                        ),
                                        child: const Icon(Icons.delete_outline, color: Colors.white54, size: 18),
                                      ),
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
        title: Text(
          'Agenda Detalhada - $nomeBarbeiro',
          style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
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
        if (mounted) {
          setState(() {
            _barbeirosComAgenda = data['equipe_agenda'] ?? [];
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
                    padding: const EdgeInsets.all(16),
                    itemCount: _barbeirosComAgenda.length,
                    itemBuilder: (context, index) {
                      final itemGrupo = _barbeirosComAgenda[index];
                      final barbeiro = itemGrupo['barbeiro'];
                      final List<dynamic> agendamentos = itemGrupo['agendamentos'];

                      return InkWell(
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
                          margin: const EdgeInsets.only(bottom: 20),
                          decoration: BoxDecoration(
                            color: _cardColor,
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(color: Colors.white.withOpacity(0.05)),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Row(
                              children: [
                                CircleAvatar(
                                  radius: 24,
                                  backgroundColor: _brandRed.withOpacity(0.2),
                                  child: Icon(Icons.content_cut, color: _brandRed, size: 22),
                                ),
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
                                  child: Text(
                                    '${agendamentos.length} agendamento(s)',
                                    style: TextStyle(color: _textSecondary, fontSize: 11, fontWeight: FontWeight.bold),
                                  ),
                                ),
                                const SizedBox(width: 4),
                                const Icon(Icons.arrow_forward_ios, color: Colors.white54, size: 14),
                              ],
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

  Future<void> _cadastrarBarbeiroAPI(String nome, String cargo, String especialidade, String telefone) async {
    try {
      final response = await http.post(
        Uri.parse(_apiUrl),
        headers: AppConfig.adminHeaders,
        body: jsonEncode({
          'nome': nome,
          'cargo': cargo,
          'especialidade': especialidade,
          'telefone': telefone,
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

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: _cardDark,
        title: const Text(
          'CADASTRAR NOVO BARBEIRO',
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
                _cadastrarBarbeiroAPI(nome, cargo, espec, fone);
              }
            },
            child: const Text('Salvar', style: TextStyle(color: Colors.white)),
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
                          CircleAvatar(
                            radius: 24,
                            backgroundColor: _brandRed.withOpacity(0.2),
                            child: Icon(Icons.content_cut, color: _brandRed, size: 24),
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
                              ],
                            ),
                          ),
                          IconButton(
                            icon: const Icon(Icons.delete_outline, color: Colors.white38),
                            onPressed: () {
                              _deletarBarbeiroAPI(b['id']);
                            },
                          ),
                        ],
                      ),
                    );
                  },
                ),
    );
  }
}