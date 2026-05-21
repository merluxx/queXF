<?php

include_once("../config.inc.php");
//include_once("../db.inc.php");
//include ("../functions/functions.output.php");

ignore_user_abort(true);
set_time_limit(0);

if (!isset($_POST['qid'])) {
    die(json_encode([
        "success" => false,
        "message" => "Missing qid"
    ]));
}

$qid = intval($_POST['qid']);
$add_scan = ($_POST['add_scan'] ?? '0') === '1';

$jobId = uniqid("zip_", true);

$tmpBase = rtrim(TEMPORARY_DIRECTORY, DIRECTORY_SEPARATOR);

$jobDir = $tmpBase . DIRECTORY_SEPARATOR . "jobs";

if (!is_dir($jobDir)) {
    mkdir($jobDir, 0777, true);
}

$statusFile = $jobDir . DIRECTORY_SEPARATOR . $jobId . ".json";
$logFile = $jobDir . DIRECTORY_SEPARATOR . $jobId . ".log";

file_put_contents($statusFile, json_encode([
    "status" => "running",
    "progress" => 0
]));

$script = realpath(dirname(__FILE__) . "/generate_zip_worker.php");
$phpCli = "/usr/bin/php";

$command =
    "nohup "
    . escapeshellcmd($phpCli)
    . " "
    . escapeshellarg($script)
    . " "
    . escapeshellarg($qid)
    . " "
    . escapeshellarg($add_scan ? "1" : "0")
    . " "
    . escapeshellarg($jobId)
    . " > "
    . escapeshellarg($logFile)
    . " 2>&1 &";

exec($command);

header('Content-Type: application/json');

echo json_encode([
    "success" => true,
    "job_id" => $jobId
]);
