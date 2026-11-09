<?php
use App\Http\Controllers\SetupController;
use Illuminate\Support\Facades\Route;
Route::redirect('/', '/admin');
Route::get('/setup', [SetupController::class,'show'])->middleware('throttle:setup')->name('setup');
Route::post('/setup', [SetupController::class,'store'])->middleware('throttle:setup');
