<?php

include_once("../config.inc.php");

$jobId = $_GET['job_id'] ?? '';

$tmpBase = rtrim(TEMPORARY_DIRECTORY, DIRECTORY_SEPARATOR);

$statusFile =
    $tmpBase
    . DIRECTORY_SEPARATOR
    . "jobs"
    . DIRECTORY_SEPARATOR
    . basename($jobId)
    . ".json";

header('Content-Type: application/json');

if (!file_exists($statusFile)) {

    echo json_encode([
        "status" => "unknown"
    ]);

    exit;
}

$data = json_decode(file_get_contents($statusFile), true);

$logFile =
    $tmpBase
    . DIRECTORY_SEPARATOR
    . "jobs"
    . DIRECTORY_SEPARATOR
    . basename($jobId)
    . ".log";

$data["log"] = "";

if (file_exists($logFile)) {
    $data["log"] = file_get_contents($logFile);
}

echo json_encode($data);
