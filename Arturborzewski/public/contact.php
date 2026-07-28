<?php
session_start();

header('Content-Type: application/json');
header('Cache-Control: no-store');

function respond(bool $success, string $message = ''): void {
    echo json_encode(['success' => $success, 'message' => $message]);
    exit;
}

// Rate limiting — max 3 submissions per 10 minutes
$now = time();
$window = 600;
$max = 3;
if (!isset($_SESSION['contact_times'])) $_SESSION['contact_times'] = [];
$_SESSION['contact_times'] = array_filter($_SESSION['contact_times'], fn($t) => ($now - $t) < $window);
if (count($_SESSION['contact_times']) >= $max) {
    respond(false, 'Zbyt wiele wiadomości. Spróbuj za chwilę.');
}

// Honeypot
if (!empty($_POST['website'])) respond(false);

// CSRF
if (
    empty($_POST['csrf_token']) ||
    empty($_SESSION['csrf_token']) ||
    !hash_equals($_SESSION['csrf_token'], $_POST['csrf_token'])
) {
    respond(false, 'Błąd weryfikacji. Odśwież stronę i spróbuj ponownie.');
}
// Invalidate token after use
unset($_SESSION['csrf_token']);

// Field validation
$imie = trim(strip_tags($_POST['imie'] ?? ''));
$email = filter_var(trim($_POST['email'] ?? ''), FILTER_VALIDATE_EMAIL);
$wiadomosc = trim(strip_tags($_POST['wiadomosc'] ?? ''));

if (!$imie || !$email || !$wiadomosc) {
    respond(false, 'Proszę wypełnić wszystkie pola.');
}
if (strlen($imie) > 100 || strlen($wiadomosc) > 5000) {
    respond(false, 'Dane przekraczają dozwoloną długość.');
}

// PHPMailer
// Requires: composer require phpmailer/phpmailer
// Or manually upload PHPMailer to public/vendor/
require_once __DIR__ . '/vendor/autoload.php';

use PHPMailer\PHPMailer\PHPMailer;
use PHPMailer\PHPMailer\SMTP;
use PHPMailer\PHPMailer\Exception;

$secrets = require __DIR__ . '/secrets.php';

$mail = new PHPMailer(true);
try {
    $mail->isSMTP();
    $mail->Host       = 'localhost';     // Or kancelaria SMTP
    $mail->SMTPAuth   = true;
    $mail->Username   = 'Kancelaria@borzewski-kancelaria.com'; // Replace
    $mail->Password   = $secrets['smtp_password'];
    $mail->SMTPAutoTLS = false;
    $mail->Port       = 25;
    $mail->Timeout    = 10;
    $mail->SMTPDebug  = SMTP::DEBUG_OFF;
    $mail->CharSet    = 'UTF-8';

    $mail->setFrom('Kancelaria@borzewski-kancelaria.com', 'Formularz — Kancelaria Borzewski');
    $mail->addAddress('Kancelaria@borzewski-kancelaria.com', 'Kancelaria Borzewski');
    $mail->addReplyTo($email, $imie);

    $mail->Subject = "Zapytanie ze strony — {$imie}";
    $mail->Body    = "Imię i nazwisko: {$imie}\nEmail: {$email}\n\nWiadomość:\n{$wiadomosc}";

    $mail->send();

    $_SESSION['contact_times'][] = $now;
    respond(true);

} catch (Exception $e) {
    error_log($e->getMessage() . "\n", 3, __DIR__ . '/mail_error.log');
    respond(false, 'Błąd wysyłania. Proszę napisać bezpośrednio na email kancelarii.');
}
